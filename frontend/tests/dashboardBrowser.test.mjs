import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const reportDir = path.join(frontendDir, 'tests', 'test-results', 'dashboard-ui')
const summaryPath = path.join(reportDir, 'summary.json')
if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before dashboard browser test')
}
mkdirSync(reportDir, { recursive: true })

const viewports = [
  { name: 'desktop-1886x1000', width: 1886, height: 1000 },
  { name: 'desktop-1536x844', width: 1536, height: 844 },
  { name: 'desktop-1280x800', width: 1280, height: 800 },
  { name: 'tablet-1024x768', width: 1024, height: 768 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'mobile-375x667', width: 375, height: 667 },
  { name: 'landscape-844x390', width: 844, height: 390 },
  { name: 'zoom-css-768x422', width: 768, height: 422 },
]
const fixedViewports = [
  { name: 'fixed-1886x1000', width: 1886, height: 1000 },
  { name: 'fixed-1536x844', width: 1536, height: 844 },
  { name: 'fixed-1536x720', width: 1536, height: 720 },
  { name: 'fixed-1280x800', width: 1280, height: 800 },
  { name: 'fixed-1280x720', width: 1280, height: 720 },
  { name: 'fixed-1257x700', width: 1257, height: 700 },
  { name: 'fixed-1100x640', width: 1100, height: 640 },
]
const state = {
  scenario: 'route-smoke',
  requests: [],
  writes: [],
  errors: [],
  profileListFailRequests: 0,
  profileListDelayNextMs: 0,
  delayedResourceLearnerId: '',
  delayedResourceMs: 0,
  delayedResponses: [],
  evidence: {
    status: 'RUNNING',
    browser: 'Microsoft Edge via Playwright channel msedge',
    viewports,
    viewportChecks: [],
    fixedLayoutChecks: [],
    scrollInputChecks: [],
    resizeModeChecks: [],
    fallbackScrollChecks: [],
    summaryStructureChecks: [],
    profilePickerChecks: [],
    profileAlignmentChecks: [],
    recommendationBranches: [],
    routeChecks: [],
    sidebarChecks: [],
    sidebarRouteChecks: [],
    sidebarAnimationChecks: [],
    sidebarMidframeChecks: [],
    sidebarKeyboardChecks: [],
    heroLayoutChecks: [],
    focusChecks: [],
    contrastChecks: [],
    reducedMotionChecks: [],
    longTextChecks: [],
    loadingChecks: [],
    browserErrors: [],
    api: { requests: [], writes: [] },
    screenshots: [],
    failures: [],
  },
}

const userFor = (scenario) => ({
  user_id: 'fixture-user',
  username: scenario === 'long-text' ? '验收用户名-' + '测试界面'.repeat(14) : 'fixture-user',
  display_name: scenario === 'long-text' ? '验收用户名-' + '测试界面'.repeat(14) : '工作台验收用户',
})
const directionFor = (scenario) => scenario === 'long-text'
  ? '跨领域复杂系统工程与研究实践方向'.repeat(5)
  : '临床数据分析'

function switchProfile(index) {
  const names = ['当前影像画像', '临床药学画像', '急救护理画像']
  const directions = ['儿科影像初阶', '临床药学进阶', '急救护理中级']
  const stages = ['初级', '进阶', '中级']
  const offset = index - 1
  const name = names[offset] || '验收画像 ' + index
  return {
    learner_id: 'learner-' + index,
    learner_type: name,
    knowledge_base_id: 'kb-' + index,
    skill_level: stages[offset] || '待诊断',
    learning_goal: '验收画像切换方向 ' + index,
    learning_preferences: { metadata: { user_profile_snapshot: { display_name: name } } },
  }
}

function profileDirectoryFor(scenario) {
  if (scenario === 'profile-switch-empty') return []
  if (scenario === 'profile-switch-single') return [switchProfile(1)]
  if (scenario === 'profile-switch-paginated') return Array.from({ length: 53 }, (_, index) => switchProfile(index + 1))
  if (['profile-switch-multiple', 'profile-switch-failure', 'profile-switch-race', 'profile-switch-loading', 'profile-switch-alignment'].includes(scenario)) {
    return [switchProfile(1), switchProfile(2), switchProfile(3)]
  }
  return null
}

function profileFor(scenario) {
  if (scenario === 'no-profile' || scenario === 'summary-failure') return []
  const directory = profileDirectoryFor(scenario)
  if (directory) return directory.slice(0, 1)
  return [{
    learner_id: 'learner-1',
    learner_type: '验收画像',
    knowledge_base_id: 'kb-1',
    skill_level: '初级',
    learning_goal: '完成一轮领域技能学习',
  }]
}

function resourceFor(scenario) {
  if (scenario !== 'with-resources') return []
  return [{
    resource_id: 'resource-1',
    id: 'resource-1',
    resource_type: 'text',
    resource_kind: 'text',
    title: '工作台验收资源',
    name: '工作台验收资源',
    status: 'published',
    created_at: '2026-10-01T10:00:00Z',
    published_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    run_id: 'run-1',
    batch_id: 'run-1',
    content_md: '# 工作台验收资源\n\n隔离 fixture 的静态内容。',
    content: '# 工作台验收资源\n\n隔离 fixture 的静态内容。',
    knowledge_points: [],
    source_refs: [],
  }]
}

function profileResources(scenario, learnerId) {
  if (scenario === 'profile-switch-race') {
    if (learnerId === 'learner-2') return profileResources('profile-switch-multiple', learnerId)
    if (learnerId === 'learner-3') return profileResources('profile-switch-multiple', learnerId)
  }
  if (scenario.startsWith('profile-switch-')) {
    if (learnerId === 'learner-2') return [profileResource(2, 1), profileResource(2, 2)]
    if (learnerId === 'learner-3') return [profileResource(3, 1), profileResource(3, 2), profileResource(3, 3)]
    return []
  }
  return learnerId === 'learner-1' ? resourceFor(scenario) : []
}

function profileResource(profileIndex, resourceIndex) {
  const hour = String(8 + resourceIndex).padStart(2, '0')
  const createdAt = `2026-10-0${profileIndex}T${hour}:00:00Z`
  return {
    resource_id: `profile-resource-${profileIndex}-${resourceIndex}`,
    id: `profile-resource-${profileIndex}-${resourceIndex}`,
    resource_type: 'text',
    resource_kind: 'text',
    title: `画像 ${profileIndex} 资源 ${resourceIndex}`,
    name: `画像 ${profileIndex} 资源 ${resourceIndex}`,
    status: 'published',
    created_at: createdAt,
    published_at: createdAt,
    updated_at: createdAt,
    run_id: `profile-run-${profileIndex}`,
    batch_id: `profile-run-${profileIndex}`,
    content_md: '# 静态画像验收资源',
    content: '# 静态画像验收资源',
    knowledge_points: [],
    source_refs: [],
  }
}

const emptyReport = {
  report_schema_version: '3.0',
  report_revision: 'rpt_' + 'a'.repeat(64),
  learner_id: 'learner-1',
  generated_at: '2026-10-01T10:00:00Z',
  as_of_profile_version: 1,
  radar: { dimensions: [], values: [] },
  weak_points: [],
  strong_points: [],
  skill_level: 'beginner',
  learning_goal: '完成一轮领域技能学习',
  difficulty_curve: [],
  metric_summary: {
    resource_count: 0,
    feedback_count: 0,
    average_correct_rate: null,
    weak_point_count: 0,
  },
  learning_activity: {
    status: 'not_measured',
    verified_attempt_count: 0,
    answered_item_count: 0,
    correct_item_count: 0,
    verified_accuracy: null,
    accuracy_delta: null,
  },
  weakness_groups: { verified_weak: [], regressing_learning: [], needs_evidence: [] },
  resource_credibility_summary: { total_count: 0, trusted_count: 0 },
  recent_resource_credibility: [],
  ability_nodes: [],
  mastery_summary: {},
  weakness_priorities: [],
  recent_resources: [],
  recent_feedback: [],
  next_suggestions: [],
  window: { window_days: 30 },
  freshness: { source_revisions: {} },
  knowledge_blind_spot_map: { schema_version: '1.0', dimensions: [], nodes: [], cells: [], summary: {} },
  resource_difficulty_curve: { schema_version: '1.0', points: [], summary: {} },
  learning_path_graph: { schema_version: '1.0', nodes: [], edges: [], current_node_ids: [], recommended_next_node_ids: [], summary: {} },
}

function json(response, body, status = 200) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  response.end(JSON.stringify(body))
}

function delayedJson(response, body, delayMs, label = '') {
  return new Promise((resolve) => setTimeout(() => {
    if (!response.destroyed) {
      json(response, body)
      if (label) state.delayedResponses.push(label)
    }
    resolve()
  }, delayMs))
}

function apiResponse(url, method, response) {
  const record = { scenario: state.scenario, method, path: url.pathname, query: url.search }
  state.requests.push(record)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    state.writes.push(record)
    return json(response, { detail: 'Read-only dashboard fixture rejects writes' }, 405)
  }

  if (url.pathname === '/api/auth/me') return json(response, { user: userFor(state.scenario) })
  if (url.pathname === '/api/profiles/') {
    if (state.scenario === 'summary-failure') {
      return json(response, { detail: 'Fixture summary failure' }, 503)
    }
    if (state.scenario === 'loading') {
      return new Promise((resolve) => setTimeout(() => {
        json(response, { items: profileFor('route-smoke') })
        resolve()
      }, 700))
    }
    const profileDirectory = profileDirectoryFor(state.scenario)
    if (profileDirectory) {
      if (state.profileListFailRequests > 0) {
        state.profileListFailRequests -= 1
        return json(response, { detail: 'Fixture profile directory failure' }, 503)
      }
      const page = Math.max(1, Number(url.searchParams.get('page') || 1))
      const pageSize = Math.max(1, Number(url.searchParams.get('page_size') || 50))
      const payload = {
        items: profileDirectory.slice((page - 1) * pageSize, page * pageSize),
        total: profileDirectory.length,
        page,
        page_size: pageSize,
      }
      if (state.profileListDelayNextMs > 0) {
        const delayMs = state.profileListDelayNextMs
        state.profileListDelayNextMs = 0
        return delayedJson(response, payload, delayMs)
      }
      return json(response, payload)
    }
    return json(response, { items: profileFor(state.scenario) })
  }
  if (url.pathname === '/api/knowledge/domains') {
    if (state.scenario === 'other-page-scroll') {
      return json(response, {
        domains: Array.from({ length: 10 }, (_, index) => ({
          domain_id: 'domain-' + (index + 1),
          name: '培训领域 ' + (index + 1),
          description: '验证普通业务页内容在短视口下仍可纵向阅读并滚动。'.repeat(2),
          tracks: [{ track_id: 'kb-' + (index + 1), knowledge_base_id: 'kb-' + (index + 1), name: '业务方向 ' + (index + 1) }],
        })),
      })
    }
    const profileDirectory = profileDirectoryFor(state.scenario)
    if (profileDirectory) {
      const directions = ['儿科影像初阶', '临床药学进阶', '急救护理中级']
      return json(response, {
        domains: [{
          domain_id: 'profile-switch-fixture',
          tracks: profileDirectory.map((profile, index) => ({
            track_id: profile.knowledge_base_id,
            knowledge_base_id: profile.knowledge_base_id,
            name: directions[index] || '画像方向-' + (index + 1),
          })),
        }],
      })
    }
    return json(response, {
      domains: [{
        domain_id: 'domain-1',
        tracks: [{ track_id: 'kb-1', knowledge_base_id: 'kb-1', name: directionFor(state.scenario) }],
      }],
    })
  }
  const learnerResourceMatch = url.pathname.match(/^\/api\/resources\/([^/]+)$/)
  if (learnerResourceMatch) {
    const learnerId = decodeURIComponent(learnerResourceMatch[1])
    const resources = profileResources(state.scenario, learnerId)
    if (state.delayedResourceLearnerId === learnerId && state.delayedResourceMs > 0) {
      const delayMs = state.delayedResourceMs
      state.delayedResourceLearnerId = ''
      state.delayedResourceMs = 0
      return delayedJson(response, { resources }, delayMs, 'resource:' + learnerId)
    }
    return json(response, { resources })
  }
  if (url.pathname === '/api/generate/jobs') {
    const learnerId = url.searchParams.get('learner_id') || 'learner-1'
    const resources = profileResources(state.scenario, learnerId)
    return json(response, {
      items: resources.length ? [{
        run_id: 'run-1',
        batch_id: 'run-1',
        resource_ids: resources.map((resource) => resource.resource_id || resource.id),
        status: 'completed',
        created_at: '2026-10-01T09:00:00Z',
        finished_at: '2026-10-01T10:00:00Z',
      }] : [],
    })
  }
  if (url.pathname === '/api/resource-library/learner-1') return json(response, [])
  if (url.pathname.startsWith('/api/learning-history/')) {
    return json(response, {
      learner_id: 'learner-1',
      profile: profileFor(state.scenario)[0] || null,
      events: [],
      rounds: [],
      next_offset: null,
    })
  }
  if (url.pathname.startsWith('/api/feedback/results/')) return json(response, [])
  if (url.pathname.startsWith('/api/feedback/evaluation/')) {
    return json(response, { learner_id: 'learner-1', questions: [], resource_ids: [], evaluation: { questions: [] } })
  }
  if (url.pathname.startsWith('/api/report/') && url.pathname.endsWith('/events')) {
    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    })
    response.end('event: report_snapshot\ndata: ' + JSON.stringify({
      learner_id: 'learner-1',
      window_days: 30,
      report_revision: emptyReport.report_revision,
    }) + '\n\n')
    return
  }
  if (url.pathname === '/api/report/learner-1') return json(response, emptyReport)
  if (url.pathname === '/api/onboarding/questions') return json(response, { questions: [] })
  if (url.pathname === '/api/skills/nodes') return json(response, { nodes: [] })
  if (url.pathname.startsWith('/api/resources/items/')) {
    const resource = resourceFor('with-resources')[0]
    return json(response, { resource })
  }
  return json(response, {
    items: [],
    profiles: [],
    domains: [],
    resources: [],
    jobs: [],
    data: [],
    user: userFor(state.scenario),
    questions: [],
    nodes: [],
    events: [],
    rounds: [],
    next_offset: null,
    report: emptyReport,
  })
}

function contentType(file) {
  return ({
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.ico': 'image/x-icon',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  })[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

function makeServer() {
  return createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://dashboard-fixture')
    const method = (request.method || 'GET').toUpperCase()
    if (url.pathname.startsWith('/api/')) {
      try {
        await apiResponse(url, method, response)
      } catch (error) {
        state.errors.push('Fixture API error: ' + error.message)
        if (!response.headersSent) json(response, { detail: 'Fixture API error' }, 500)
        else response.destroy(error)
      }
      return
    }

    let decoded
    try {
      decoded = decodeURIComponent(url.pathname)
    } catch {
      response.writeHead(400)
      response.end('Invalid path')
      return
    }
    const candidate = path.resolve(distDir, '.' + decoded)
    const safe = candidate === distDir || candidate.startsWith(distDir + path.sep)
    const isFile = safe && existsSync(candidate) && statSync(candidate).isFile()
    const file = isFile ? candidate : path.join(distDir, 'index.html')
    if (!existsSync(file)) {
      response.writeHead(404)
      response.end('Not found')
      return
    }
    response.writeHead(200, { 'content-type': contentType(file), 'cache-control': 'no-cache' })
    response.end(readFileSync(file))
  })
}

async function newFixturePage(browser, base, viewport, scenario, { trackResizeObserver = false } = {}) {
  state.scenario = scenario
  state.profileListFailRequests = 0
  state.profileListDelayNextMs = 0
  state.delayedResourceLearnerId = ''
  state.delayedResourceMs = 0
  state.delayedResponses = []
  if (scenario === 'profile-switch-loading') state.profileListDelayNextMs = 650
  if (scenario === 'profile-switch-failure') state.profileListFailRequests = 1
  const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } })
  page.setDefaultTimeout(8000)
  page.on('pageerror', (error) => state.evidence.browserErrors.push({
    type: 'pageerror',
    url: page.url(),
    message: error.message,
  }))
  await page.addInitScript(() => {
    const marker = '__dashboard_fixture_storage_initialized'
    if (sessionStorage.getItem(marker)) return
    localStorage.clear()
    sessionStorage.setItem(marker, '1')
  })
  if (trackResizeObserver) {
    await page.addInitScript(() => {
      const NativeResizeObserver = window.ResizeObserver
      if (typeof NativeResizeObserver !== 'function' || window.__dashboardResizeObserverWrapped) return
      window.__dashboardResizeObserverWrapped = true
      window.__dashboardResizeObserverCallbacks = 0
      window.ResizeObserver = class extends NativeResizeObserver {
        constructor(callback) {
          super((entries, observer) => {
            window.__dashboardResizeObserverCallbacks += 1
            callback(entries, observer)
          })
        }
      }
    })
  }
  await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
  await page.locator('.home-page').waitFor()
  await page.locator('.learning-summary').waitFor()
  return page
}

async function waitForSummary(page) {
  await page.waitForFunction(() => {
    const summary = document.querySelector('.learning-summary')
    return summary && summary.getAttribute('aria-busy') === 'false'
  })
}

async function waitForDashboard(page) {
  await page.locator('.home-page').waitFor()
  await waitForSummary(page)
  await page.evaluate(() => document.fonts.ready)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function openProfileDialog(page) {
  await page.locator('.workspace-switch').click()
  const dialog = page.locator('.el-dialog.profile-switch-dialog')
  await dialog.waitFor({ state: 'visible' })
  assert.equal((await dialog.locator('.el-dialog__title').innerText()).trim(), '切换学习画像')
  return dialog
}

async function closeProfileDialog(page) {
  await page.locator('.el-dialog.profile-switch-dialog').waitFor({ state: 'hidden' })
  const focusReturned = await page.evaluate(() => document.activeElement?.matches('.workspace-switch') === true)
  assert.equal(focusReturned, true, 'closing the profile dialog should return focus to its trigger')
}

async function profileDashboardSnapshot(page) {
  return page.evaluate(() => ({
    labels: [...document.querySelectorAll('.summary-item')].map((item) => item.querySelector('.summary-label')?.textContent.trim() || ''),
    values: [...document.querySelectorAll('.summary-item')].map((item) => item.querySelector('.summary-value strong')?.textContent.trim() || ''),
    recommendation: document.querySelector('.next-action-title')?.textContent.trim() || '',
    primary: document.querySelector('.workbench-primary')?.innerText.trim() || '',
    primaryDisabled: document.querySelector('.workbench-primary')?.matches(':disabled') || false,
    heroBusy: document.querySelector('.home-hero')?.getAttribute('aria-busy') || '',
    summaryBusy: document.querySelector('.learning-summary')?.getAttribute('aria-busy') || '',
    currentLearnerId: localStorage.getItem('last_learner_id') || '',
    directionId: localStorage.getItem('learning_direction_id') || '',
    directionName: localStorage.getItem('learning_direction_name') || '',
    currentProfile: (() => {
      try { return JSON.parse(localStorage.getItem('current_profile') || 'null')?.learner_id || '' } catch { return '' }
    })(),
  }))
}

async function waitForProfileDashboard(page, expected) {
  await page.waitForFunction((target) => {
    const summary = document.querySelector('.learning-summary')
    const hero = document.querySelector('.home-hero')
    const values = [...document.querySelectorAll('.summary-item')].map((item) => item.querySelector('.summary-value strong')?.textContent.trim() || '')
    return summary?.getAttribute('aria-busy') === 'false'
      && hero?.getAttribute('aria-busy') === 'false'
      && values[0] === target.direction
      && values[1] === target.stage
      && values[2].includes(target.resources)
      && (!target.timeContains || values[3].includes(target.timeContains))
      && document.querySelector('.next-action-title')?.textContent.trim() === target.recommendation
  }, expected)
}

async function waitForFixture(predicate, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20))
  assert.ok(predicate(), message)
}

function profileRequestPages(requests = state.requests) {
  return requests.filter((request) => request.path === '/api/profiles/').map((request) => {
    const params = new URLSearchParams(request.query)
    return { page: Number(params.get('page') || 1), pageSize: Number(params.get('page_size') || 10) }
  })
}

async function geometry(page, label, recordViewport = true) {
  const metrics = await page.evaluate(() => {
    const selectors = ['document.documentElement', 'document.body', '.app-shell', '.main-area', '.content-area', '.home-page']
    const widths = Object.fromEntries(selectors.map((selector) => {
      const node = selector === 'document.documentElement'
        ? document.documentElement
        : selector === 'document.body'
          ? document.body
          : document.querySelector(selector)
      return [selector, node ? {
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
        left: node.getBoundingClientRect().left,
        right: node.getBoundingClientRect().right,
      } : null]
    }))
    const viewport = { width: innerWidth, height: innerHeight }
    const horizontallyOffscreenActions = [...document.querySelectorAll('.sidebar-toggle, .topbar-action, .workbench-primary, .workbench-history, .workspace-new, .tool-card')]
      .filter((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
          && (rect.left < -1 || rect.right > innerWidth + 1)
      })
      .map((node) => ({ selector: node.className, left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right }))
    return { viewport, widths, horizontallyOffscreenActions }
  })
  for (const [selector, width] of Object.entries(metrics.widths)) {
    if (!width) continue
    assert.ok(width.scrollWidth <= width.clientWidth + 1, label + ': horizontal overflow in ' + selector + ' ' + JSON.stringify(width))
    assert.ok(width.left >= -1 && width.right <= metrics.viewport.width + 1, label + ': container outside viewport in ' + selector)
  }
  assert.deepEqual(metrics.horizontallyOffscreenActions, [], label + ': visible actions extend beyond the viewport')
  if (recordViewport) state.evidence.viewportChecks.push({ label, ...metrics })
  return metrics
}

async function actionReachable(page, selector, label) {
  const target = page.locator(selector).first()
  await target.waitFor({ state: 'visible' })
  await target.scrollIntoViewIfNeeded()
  const result = await target.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return {
      visible: rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden',
      inViewport: rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1,
      centerHit: hit === node || node.contains(hit),
      href: node.getAttribute('href'),
      text: node.innerText?.trim() || node.getAttribute('aria-label') || '',
    }
  })
  assert.equal(result.visible, true, label + ': control is not visible')
  assert.equal(result.inViewport, true, label + ': control cannot be brought into the viewport')
  assert.equal(result.centerHit, true, label + ': another element obscures the control center')
  return result
}

async function assertRouteClick(page, selector, expectedPath, label) {
  const beforeErrors = state.evidence.browserErrors.length
  const target = page.locator(selector).first()
  await target.waitFor({ state: 'visible' })
  await target.scrollIntoViewIfNeeded()
  await target.click()
  await page.waitForFunction((pathName) => location.pathname === pathName, expectedPath)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  assert.equal(state.evidence.browserErrors.length, beforeErrors, label + ': browser exception during route navigation')
  const result = { label, expectedPath, actualPath: new URL(page.url()).pathname }
  state.evidence.routeChecks.push(result)
  return result
}

async function textContrast(page, selectors) {
  const results = await page.evaluate((items) => {
    const parseColor = (value) => {
      const match = String(value).match(/^rgba?\((.*)\)$/i)
      if (!match) throw new Error('Unsupported computed color: ' + value)
      const parts = match[1].replace(/\//g, ',').split(/[,\s]+/).filter(Boolean)
      const channel = (item) => item.endsWith('%')
        ? Math.round(Number.parseFloat(item) * 2.55)
        : Number.parseFloat(item)
      const alpha = parts.length > 3 ? (parts[3].endsWith('%') ? Number.parseFloat(parts[3]) / 100 : Number.parseFloat(parts[3])) : 1
      return [channel(parts[0]), channel(parts[1]), channel(parts[2]), alpha]
    }
    const over = (foreground, background) => {
      const alpha = foreground[3]
      return [
        foreground[0] * alpha + background[0] * (1 - alpha),
        foreground[1] * alpha + background[1] * (1 - alpha),
        foreground[2] * alpha + background[2] * (1 - alpha),
        1,
      ]
    }
    const relativeLuminance = (color) => {
      const values = color.slice(0, 3).map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
    }
    const contrast = (first, second) => {
      const left = relativeLuminance(first)
      const right = relativeLuminance(second)
      return (Math.max(left, right) + 0.05) / (Math.min(left, right) + 0.05)
    }
    return items.flatMap((selector) => {
      const nodes = [...document.querySelectorAll(selector)]
      if (!nodes.length) return [{ selector, missing: true }]
      return nodes.map((node, index) => {
        const label = nodes.length > 1 ? selector + '[' + index + ']' : selector
        const ancestors = []
        for (let current = node; current instanceof Element; current = current.parentElement) ancestors.push(current)
        const chain = ancestors.reverse()
        let background = [255, 255, 255, 1]
        for (const current of chain) {
          const style = getComputedStyle(current)
          if (style.backgroundImage !== 'none') {
            throw new Error(label + ': contrast background contains an image/gradient at ' + current.className)
          }
          if (Number.parseFloat(style.opacity) < 0.999) {
            throw new Error(label + ': opacity group prevents reliable composed contrast at ' + current.className)
          }
          if (style.mixBlendMode !== 'normal') {
            throw new Error(label + ': non-normal blend mode prevents reliable composed contrast at ' + current.className)
          }
          background = over(parseColor(style.backgroundColor), background)
        }
        const style = getComputedStyle(node)
        const foreground = over(parseColor(style.color), background)
        return {
          selector: label,
          text: node.textContent.trim(),
          color: style.color,
          composedBackground: 'rgb(' + background.slice(0, 3).map(Math.round).join(', ') + ')',
          contrast: Number(contrast(foreground, background).toFixed(2)),
          fontSize: style.fontSize,
        }
      })
    })
  }, selectors)
  for (const result of results) {
    assert.notEqual(result.missing, true, 'Contrast target is missing: ' + result.selector)
    assert.ok(result.text, 'Contrast target has no text: ' + result.selector)
    assert.ok(result.contrast >= 4.5, result.selector + ' contrast ' + result.contrast + ' is below 4.5:1')
  }
  return results
}

async function checkViewportState(page, viewport, collapsed, captureScreenshot = true) {
  const stateName = collapsed ? 'collapsed' : 'expanded'
  await page.waitForFunction((expected) => {
    const shell = document.querySelector('.app-shell')
    return shell && shell.classList.contains('is-sidebar-collapsed') === expected
      && !shell.classList.contains('is-sidebar-animating')
  }, collapsed)
  await geometry(page, viewport.name + ' ' + stateName)
  const finalTool = page.locator('.tool-card').last()
  await finalTool.scrollIntoViewIfNeeded()
  const finalRect = await finalTool.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return { top: rect.top, bottom: rect.bottom, visible: rect.width > 0 && rect.height > 0, centerHit: hit === node || node.contains(hit) }
  })
  assert.equal(finalRect.visible, true, viewport.name + ' ' + stateName + ': last tool is unreachable')
  assert.ok(finalRect.top >= -1 && finalRect.bottom <= viewport.height + 1, viewport.name + ' ' + stateName + ': last tool cannot be scrolled into view')
  assert.equal(finalRect.centerHit, true, viewport.name + ' ' + stateName + ': last tool is obscured')
  await page.locator('.home-page').evaluate((node) => {
    const scrollable = node.closest('.content-area')
    if (scrollable) scrollable.scrollTop = 0
    else window.scrollTo(0, 0)
  })
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  if (captureScreenshot) {
    const filename = 'dashboard-' + viewport.name + '-' + stateName + '.png'
    const buffer = await page.screenshot({ path: path.join(reportDir, filename) })
    state.evidence.screenshots.push({
      filename,
      width: buffer.readUInt32BE(16),
      height: buffer.readUInt32BE(20),
      viewport: { width: viewport.width, height: viewport.height },
    })
  }
}

async function fixedLayoutSnapshot(page, label, collapsed) {
  const result = await page.evaluate(() => {
    const content = document.querySelector('.content-area')
    const bounds = content?.getBoundingClientRect()
    const selectors = [
      '.workspace-heading', '.home-hero', '.learning-summary', '.workspace-grid',
      '.learning-tools', '.tool-grid', '.learning-route-panel', '.route-list', '.workspace-footer',
      '.workspace-new', '.workspace-switch', '.workbench-primary', '.workbench-history', '.tool-card',
    ]
    const requiredText = [
      '.workspace-heading h2', '.workspace-heading p', '.hero-copy h2', '.next-action-title', '.hero-copy p',
      '.hero-actions .workbench-primary', '.hero-actions .workbench-history', '.workspace-new', '.workspace-switch',
      '.summary-label', '.summary-value strong',
      '.tool-copy strong', '.tool-copy small', '.learning-route-panel .section-heading h3',
      '.route-list li span', '.route-list li small', '.workspace-footer span',
    ]
    const visible = (node) => {
      if (!node) return false
      const style = getComputedStyle(node)
      const rect = node.getBoundingClientRect()
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
        && node.getClientRects().length > 0
    }
    const contained = (node) => {
      if (!visible(node) || !bounds) return false
      const rect = node.getBoundingClientRect()
      return rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1
        && rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1
        && rect.top >= -1 && rect.bottom <= innerHeight + 1
    }
    const overflowSelectors = [
      'document.documentElement', 'document.body', '#app', '.app-shell', '.content-area', '.home-page',
      '.home-hero', '.tool-grid', '.learning-route-panel',
    ]
    const overflow = Object.fromEntries(overflowSelectors.map((selector) => {
      const node = selector === 'document.documentElement' ? document.documentElement
        : selector === 'document.body' ? document.body
          : document.querySelector(selector)
      return [selector, node ? {
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        scrollTop: node.scrollTop,
        overflowY: getComputedStyle(node).overflowY,
      } : null]
    }))
    const offscreen = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]
      .filter((node) => visible(node) && !contained(node))
      .map((node) => ({ selector, text: node.innerText?.trim().slice(0, 80) || '', rect: (() => {
        const rect = node.getBoundingClientRect()
        return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }
      })() })))
    const hiddenText = requiredText.flatMap((selector) => [...document.querySelectorAll(selector)]
      .filter((node) => !visible(node) || !contained(node) || !node.textContent.trim())
      .map((node) => ({ selector, text: node.textContent.trim() })))
    const summaryItems = [...document.querySelectorAll('.summary-item')].map((item) => {
      const label = item.querySelector('.summary-label')
      const value = item.querySelector('.summary-value')
      const code = item.querySelector('.summary-code')
      const icon = item.querySelector('.summary-icon')
      const iconSvg = icon?.querySelector('svg')
      return {
        label: label?.textContent.trim() || '',
        value: value?.innerText.trim() || '',
        code: code?.textContent.trim() || '',
        labelVisible: visible(label) && contained(label),
        valueVisible: visible(value) && contained(value),
        codeVisible: visible(code) && contained(code),
        iconVisible: visible(icon) && contained(icon) && visible(iconSvg) && contained(iconSvg),
      }
    })
    const shell = document.querySelector('.app-shell')
    const home = document.querySelector('.home-page')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      shellFit: Boolean(home?.classList.contains('is-fit-layout')),
      shellCollapsed: Boolean(shell?.classList.contains('is-sidebar-collapsed')),
      contentBounds: bounds ? { top: bounds.top, bottom: bounds.bottom, height: bounds.height } : null,
      nodes: Object.fromEntries(selectors.map((selector) => [selector, [...document.querySelectorAll(selector)].map((node) => {
        const rect = node.getBoundingClientRect()
        return { text: node.innerText?.trim().slice(0, 90) || '', top: rect.top, bottom: rect.bottom, visible: visible(node) }
      })])),
      overflow,
      offscreen,
      hiddenText,
      summaryItems,
    }
  })
  assert.equal(result.shellFit, true, label + ': eligible desktop did not enable measured fit layout')
  assert.equal(result.shellCollapsed, collapsed, label + ': sidebar state changed during fit check')
  assert.deepEqual(result.offscreen, [], label + ': fixed content or controls are outside the initial content viewport')
  assert.deepEqual(result.hiddenText, [], label + ': fixed dashboard text is missing, clipped or outside the first viewport')
  for (const [selector, metrics] of Object.entries(result.overflow)) {
    if (!metrics) continue
    assert.ok(metrics.scrollHeight <= metrics.clientHeight + 1, label + ': vertical overflow in ' + selector + ' ' + JSON.stringify(metrics))
    assert.equal(metrics.scrollTop, 0, label + ': unexpected initial scrollTop in ' + selector)
  }
  assert.equal(result.summaryItems.length, 4, label + ': all four summary metrics must remain visible')
  for (const item of result.summaryItems) {
    assert.ok(item.label && item.value && item.code, label + ': summary label, value and code must have content ' + JSON.stringify(item))
    assert.equal(item.labelVisible && item.valueVisible && item.iconVisible, true,
      label + ': summary icon, label and value must fit and remain visible ' + JSON.stringify(item))
    if (result.viewport.height > 720) {
      assert.equal(item.codeVisible, true, label + ': summary metadata code should be visible above 720px ' + JSON.stringify(item))
    }
  }
  const resourceMetric = result.summaryItems.find((item) => item.label.includes('资源'))
  assert.ok(resourceMetric?.value.includes('1 份'), label + ': resource summary must display the complete value “1 份”')
  state.evidence.fixedLayoutChecks.push({ label, ...result })
  return result
}

async function assertFixedLayoutDoesNotScroll(page, label) {
  const positions = () => page.evaluate(() => {
    const selectors = ['document.documentElement', 'document.body', '#app', '.app-shell', '.content-area', '.home-page']
    return Object.fromEntries(selectors.map((selector) => {
      const node = selector === 'document.documentElement' ? document.documentElement
        : selector === 'document.body' ? document.body
          : document.querySelector(selector)
      return [selector, node?.scrollTop ?? null]
    }).concat([['window.scrollY', window.scrollY]]))
  })
  const before = await positions()
  await page.mouse.move(Math.round(page.viewportSize().width * 0.75), Math.round(page.viewportSize().height * 0.7))
  await page.mouse.wheel(0, 700)
  await page.waitForTimeout(80)
  const afterWheel = await positions()
  await page.keyboard.press('PageDown')
  await page.keyboard.press('End')
  await page.waitForTimeout(80)
  const afterKeyboard = await positions()
  await page.evaluate(() => {
    window.scrollTo(0, 500)
    for (const selector of ['document.documentElement', 'document.body', '#app', '.app-shell', '.content-area', '.home-page']) {
      const node = selector === 'document.documentElement' ? document.documentElement
        : selector === 'document.body' ? document.body
          : document.querySelector(selector)
      if (node) node.scrollTop = 500
    }
  })
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const afterProgrammatic = await positions()
  for (const [phase, current] of Object.entries({ afterWheel, afterKeyboard, afterProgrammatic })) {
    assert.deepEqual(current, before, label + ': ' + phase + ' changed a fixed desktop scroll position')
  }
  state.evidence.scrollInputChecks.push({ label, before, afterWheel, afterKeyboard, afterProgrammatic })
}

async function testDesktopFixedLayout(browser, base) {
  for (const viewport of fixedViewports) {
    for (const collapsed of [false, true]) {
      const page = await newFixturePage(browser, base, viewport, 'with-resources')
      try {
        await waitForDashboard(page)
        if (collapsed) await page.locator('.sidebar-toggle').click()
      await waitForSidebarState(page, collapsed)
        await fixedLayoutSnapshot(page, viewport.name + (collapsed ? ' collapsed' : ' expanded'), collapsed)
        await assertFixedLayoutDoesNotScroll(page, viewport.name + (collapsed ? ' collapsed' : ' expanded'))
        const filename = 'dashboard-' + viewport.name + (collapsed ? '-collapsed' : '-expanded') + '-fixed.png'
        const buffer = await page.screenshot({ path: path.join(reportDir, filename) })
        state.evidence.screenshots.push({
          filename,
          width: buffer.readUInt32BE(16),
          height: buffer.readUInt32BE(20),
          viewport: { width: viewport.width, height: viewport.height },
        })
      } finally {
        await page.close()
      }
    }
  }
}

async function waitForFitMode(page, expected) {
  await page.waitForFunction((fit) => document.querySelector('.home-page')?.classList.contains('is-fit-layout') === fit, expected)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function testResizeAndNaturalReading(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1536, height: 844 }, 'with-resources')
  try {
    await waitForDashboard(page)
    await waitForFitMode(page, true)
    await fixedLayoutSnapshot(page, 'resize-start-1536x844', false)

    await page.setViewportSize({ width: 390, height: 844 })
    await waitForFitMode(page, false)
    const mobileState = await page.evaluate(() => {
      const content = document.querySelector('.content-area')
      const home = document.querySelector('.home-page')
      const lastTool = document.querySelector('.tool-card:last-child')
      return {
        fit: home?.classList.contains('is-fit-layout'),
        content: content ? { clientHeight: content.clientHeight, scrollHeight: content.scrollHeight, scrollTop: content.scrollTop } : null,
        lastToolBottom: lastTool?.getBoundingClientRect().bottom ?? null,
        viewportHeight: innerHeight,
      }
    })
    assert.equal(mobileState.fit, false, 'mobile resize should return to natural reading layout')
    assert.ok(mobileState.content?.scrollHeight > mobileState.content?.clientHeight + 1, 'mobile dashboard should retain natural vertical content')
    assert.ok(mobileState.lastToolBottom > mobileState.viewportHeight, 'mobile dashboard should expose later content through natural scroll')
    await page.locator('.tool-card:last-child').scrollIntoViewIfNeeded()
    const mobileReached = await page.locator('.tool-card:last-child').evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return rect.top >= -1 && rect.bottom <= innerHeight + 1 && rect.height > 0
    })
    assert.equal(mobileReached, true, 'mobile natural reading should reach the last tool')
    const mobileScrollTop = await page.locator('.content-area').evaluate((node) => node.scrollTop)
    assert.ok(mobileScrollTop > 0, 'mobile natural reading should change content-area scrollTop')
    state.evidence.resizeModeChecks.push({ from: '1536x844', to: '390x844', mobileState, mobileScrollTop, lastToolReachable: mobileReached })

    await page.setViewportSize({ width: 1536, height: 844 })
    await waitForFitMode(page, true)
    const restored = await fixedLayoutSnapshot(page, 'resize-restored-1536x844', false)
    await assertFixedLayoutDoesNotScroll(page, 'resize-restored-1536x844')
    state.evidence.resizeModeChecks.push({ from: '390x844', to: '1536x844', fitRestored: restored.shellFit })
  } finally {
    await page.close()
  }
}

async function testLongDirectionDesktopFallback(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'long-text')
  try {
    await waitForDashboard(page)
    await waitForFitMode(page, false)
    const result = await page.evaluate(() => {
      const direction = document.querySelector('.hero-copy h2')
      const content = document.querySelector('.content-area')
      const home = document.querySelector('.home-page')
      const rect = direction?.getBoundingClientRect()
      const style = direction ? getComputedStyle(direction) : null
      return {
        fit: home?.classList.contains('is-fit-layout'),
        directionText: direction?.textContent.trim() || '',
        directionRect: rect ? { top: rect.top, bottom: rect.bottom, height: rect.height } : null,
        directionStyle: style ? { whiteSpace: style.whiteSpace, overflow: style.overflow, textOverflow: style.textOverflow, scrollHeight: direction.scrollHeight, clientHeight: direction.clientHeight, scrollWidth: direction.scrollWidth, clientWidth: direction.clientWidth } : null,
        content: content ? { clientHeight: content.clientHeight, scrollHeight: content.scrollHeight, scrollTop: content.scrollTop } : null,
      }
    })
    assert.equal(result.fit, false, 'a long learning direction should disable desktop fixed mode')
    assert.ok(result.directionText.includes(directionFor('long-text')), 'long direction must remain present')
    assert.notEqual(result.directionStyle?.whiteSpace, 'nowrap', 'long direction must wrap')
    assert.ok(result.directionStyle?.scrollWidth <= result.directionStyle?.clientWidth + 1, 'long direction must not clip horizontally')
    assert.ok(result.directionStyle?.scrollHeight <= result.directionStyle?.clientHeight + 1, 'long direction must not clip vertically')
    assert.ok(result.content?.scrollHeight > result.content?.clientHeight + 1, 'long direction should return the page to natural scrolling')
    await page.locator('.workspace-footer').scrollIntoViewIfNeeded()
    const reachedEnd = await page.locator('.workspace-footer').evaluate((node) => {
      const rect = node.getBoundingClientRect()
      const content = node.closest('.content-area')
      return {
        rect: { top: rect.top, bottom: rect.bottom, height: rect.height },
        viewportHeight: innerHeight,
        contentScrollTop: content?.scrollTop ?? null,
        contentScrollHeight: content?.scrollHeight ?? null,
        contentClientHeight: content?.clientHeight ?? null,
      }
    })
    assert.ok(reachedEnd.contentScrollTop > 0, 'long direction fallback should allow scrolling through natural dashboard content to its footer: ' + JSON.stringify(reachedEnd))
    assert.ok(reachedEnd.rect.top >= -1 && reachedEnd.rect.bottom <= reachedEnd.viewportHeight + 1,
      'natural dashboard scroll should make the footer fully readable: ' + JSON.stringify(reachedEnd))
    const directionStillReadable = await page.locator('.hero-copy h2').evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return node.textContent.trim().length > 0 && rect.height > 0 && node.scrollHeight <= node.clientHeight + 1
    })
    assert.equal(directionStillReadable, true, 'long direction should remain readable after scrolling')
    state.evidence.fallbackScrollChecks.push({ kind: 'long-direction-desktop', ...result, reachedEnd, directionStillReadable })
  } finally {
    await page.close()
  }
}

async function testOtherBusinessPageScroll(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'other-page-scroll')
  try {
    await page.goto(base + '/learning/new', { waitUntil: 'domcontentloaded' })
    await page.locator('.onboarding-page').waitFor()
    await page.locator('.domain-stage-card').waitFor()
    await page.waitForFunction(() => document.querySelector('.app-shell') && !document.querySelector('.app-shell').classList.contains('is-dashboard'))
    const layoutSelectors = ['.domain-stage-card .el-card__body', '.content-area', '.onboarding-page', '.step-panel', '.wizard-layout']
    const inspectLayout = () => page.evaluate((selectors) => ({
      viewport: { width: innerWidth, height: innerHeight },
      shellClass: document.querySelector('.app-shell')?.className ?? null,
      onboardingClass: document.querySelector('.onboarding-page')?.className ?? null,
      domainCount: document.querySelectorAll('.domain-stage-card .choice-card').length,
      candidates: selectors.map((selector) => {
        const node = document.querySelector(selector)
        if (!node) return { selector, present: false }
        const style = getComputedStyle(node)
        return {
          selector,
          present: true,
          clientHeight: node.clientHeight,
          scrollHeight: node.scrollHeight,
          scrollTop: node.scrollTop,
          overflowY: style.overflowY,
        }
      }),
    }), layoutSelectors)
    const waitForStableLayout = async () => {
      await page.waitForFunction(() => document.querySelectorAll('.domain-stage-card .choice-card').length === 10)
      await page.evaluate(() => document.fonts.ready)
      await page.waitForFunction((selectors) => {
        const root = document.querySelector('.onboarding-page')
        const shell = document.querySelector('.app-shell')
        const snapshot = selectors.map((selector) => {
          const node = document.querySelector(selector)
          if (!node) return [selector, null]
          const style = getComputedStyle(node)
          return [selector, node.clientHeight, node.scrollHeight, node.scrollTop, style.overflowY]
        })
        const signature = JSON.stringify({
          viewport: [innerWidth, innerHeight],
          shellClass: shell?.className ?? null,
          onboardingClass: root?.className ?? null,
          domainCount: document.querySelectorAll('.domain-stage-card .choice-card').length,
          snapshot,
        })
        if (window.__dashboardOtherPageLayoutSignature === signature) {
          window.__dashboardOtherPageLayoutStableFrames = (window.__dashboardOtherPageLayoutStableFrames || 0) + 1
        } else {
          window.__dashboardOtherPageLayoutSignature = signature
          window.__dashboardOtherPageLayoutStableFrames = 0
        }
        return window.__dashboardOtherPageLayoutStableFrames >= 4
      }, layoutSelectors, { polling: 'raf', timeout: 9000 })
    }
    await waitForStableLayout()
    let viewport = { width: 1280, height: 800 }
    const chooseScrollTarget = async () => page.evaluate(() => {
      const selectors = ['.domain-stage-card .el-card__body', '.content-area', '.onboarding-page', '.step-panel', '.wizard-layout']
      for (const selector of selectors) {
        const node = document.querySelector(selector)
        if (!node) continue
        const style = getComputedStyle(node)
        if (node.scrollHeight > node.clientHeight + 1 && ['auto', 'scroll'].includes(style.overflowY)) {
          return { selector, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowY: style.overflowY }
        }
      }
      return null
    })
    let target = await chooseScrollTarget()
    if (!target) {
      viewport = { width: 1280, height: 600 }
      await page.setViewportSize(viewport)
      await waitForStableLayout()
      target = await chooseScrollTarget()
    }
    assert.ok(target, 'ordinary onboarding page must expose a real scroll container at 1280x800 or 1280x600: ' + JSON.stringify(await inspectLayout()))
    const before = await page.locator(target.selector).evaluate((node) => node.scrollTop)
    await page.locator(target.selector).evaluate((node) => { node.scrollTop = Math.min(node.scrollTop + 160, node.scrollHeight) })
    const programmaticFrames = await page.locator(target.selector).evaluate(async (node) => {
      const values = []
      for (let frame = 0; frame < 4; frame += 1) {
        await new Promise((resolve) => requestAnimationFrame(resolve))
        values.push(node.scrollTop)
      }
      return values
    })
    const afterProgrammatic = await page.locator(target.selector).evaluate((node) => node.scrollTop)
    assert.ok(afterProgrammatic > before && programmaticFrames.every((value) => value > before),
      'ordinary onboarding page programmatic scroll should remain effective after layout settles: ' + JSON.stringify({ before, afterProgrammatic, programmaticFrames, layout: await inspectLayout() }))
    const box = await page.locator(target.selector).boundingBox()
    let wheelStart = null
    let wheelFrames = []
    if (box) {
      await page.locator(target.selector).evaluate((node) => { node.scrollTop = 0 })
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      wheelStart = await page.locator(target.selector).evaluate((node) => node.scrollTop)
      await page.mouse.move(box.x + Math.min(box.width / 2, 200), box.y + Math.min(box.height / 2, 150))
      await page.mouse.wheel(0, 220)
      wheelFrames = await page.locator(target.selector).evaluate(async (node) => {
        const values = []
        for (let frame = 0; frame < 4; frame += 1) {
          await new Promise((resolve) => requestAnimationFrame(resolve))
          values.push(node.scrollTop)
        }
        return values
      })
    }
    const afterWheel = await page.locator(target.selector).evaluate((node) => node.scrollTop)
    assert.ok(wheelStart === 0 && afterWheel > wheelStart && wheelFrames.every((value) => value > wheelStart),
      'ordinary onboarding page should actually scroll after wheel input from the top: ' + JSON.stringify({ wheelStart, afterWheel, wheelFrames, layout: await inspectLayout() }))
    state.evidence.fallbackScrollChecks.push({ kind: 'other-business-page', route: '/learning/new', viewport, ...target, before, afterProgrammatic, programmaticFrames, wheelStart, afterWheel, wheelFrames, layout: await inspectLayout() })
  } finally {
    await page.close()
  }
}

async function testProfilePickerEmptyAndSingle(browser, base) {
  const emptyPage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-empty')
  try {
    await waitForDashboard(emptyPage)
    const dialog = await openProfileDialog(emptyPage)
    await dialog.locator('.profile-switch-empty').waitFor({ state: 'visible' })
    assert.equal(await dialog.locator('.profile-option').count(), 0, 'empty profile directory should not render selectable options')
    const create = dialog.locator('.profile-switch-create')
    await create.waitFor({ state: 'visible' })
    await create.click()
    await emptyPage.waitForFunction(() => location.pathname === '/learning/new')
    state.evidence.profilePickerChecks.push({ scenario: 'empty-directory', options: 0, createPath: new URL(emptyPage.url()).pathname })
  } finally {
    await emptyPage.close()
  }

  const singlePage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-single')
  try {
    await waitForDashboard(singlePage)
    const before = await profileDashboardSnapshot(singlePage)
    const dialog = await openProfileDialog(singlePage)
    assert.equal(await dialog.locator('.profile-option').count(), 1, 'single profile should render one option')
    assert.equal(await dialog.locator('.profile-option').getAttribute('data-learner-id'), 'learner-1')
    assert.equal(await dialog.locator('.profile-option').getAttribute('aria-pressed'), 'true', 'the only profile should be marked current')
    await dialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(singlePage)
    const after = await profileDashboardSnapshot(singlePage)
    assert.deepEqual(after, before, 'cancel should leave a single current profile unchanged')
    state.evidence.profilePickerChecks.push({ scenario: 'single-profile', optionCount: 1, ariaPressed: 'true', cancelPreservedState: true })
  } finally {
    await singlePage.close()
  }
}

async function testProfilePickerSelectionPersistenceAndKeyboard(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-multiple')
  try {
    await waitForDashboard(page)
    const initial = await profileDashboardSnapshot(page)
    assert.deepEqual(initial.labels, ['当前方向', '当前画像阶段', '已生成资源数量', '最近一次学习时间'])
    assert.deepEqual(initial.values.slice(0, 3), ['儿科影像初阶', '初级', '0 份'])
    assert.equal(initial.recommendation, '生成第一批学习资源')
    assert.equal(initial.currentLearnerId, 'learner-1')

    const cancelDialog = await openProfileDialog(page)
    assert.equal(await cancelDialog.locator('.profile-option').count(), 3, 'multi-profile directory should render all three options')
    assert.deepEqual(await cancelDialog.locator('.profile-option').evaluateAll((items) => items.map((item) => item.getAttribute('aria-pressed'))), ['true', 'false', 'false'])
    await cancelDialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(page)
    assert.deepEqual(await profileDashboardSnapshot(page), initial, 'cancel should not change the selected profile or dashboard data')

    const closeDialog = await openProfileDialog(page)
    await closeDialog.locator('.el-dialog__headerbtn').click()
    await closeProfileDialog(page)
    assert.deepEqual(await profileDashboardSnapshot(page), initial, 'dialog close should not change the selected profile or dashboard data')

    await openProfileDialog(page)
    await page.keyboard.press('Escape')
    await closeProfileDialog(page)
    assert.deepEqual(await profileDashboardSnapshot(page), initial, 'Escape should not change the selected profile or dashboard data')

    await page.locator('.workspace-switch').focus()
    await page.keyboard.press('Enter')
    const selectionDialog = page.locator('.el-dialog.profile-switch-dialog')
    await selectionDialog.waitFor({ state: 'visible' })
    const secondOption = selectionDialog.locator('.profile-option[data-learner-id="learner-2"]')
    assert.equal((await secondOption.locator('.profile-option-name').innerText()).trim(), '临床药学画像')
    assert.equal((await secondOption.locator('.profile-option-direction').innerText()).trim(), '临床药学进阶')
    assert.equal((await secondOption.locator('.profile-option-stage').innerText()).trim(), '进阶')
    let keyboardFocused = false
    for (let index = 0; index < 16; index += 1) {
      keyboardFocused = await secondOption.evaluate((node) => document.activeElement === node)
      if (keyboardFocused) break
      await page.keyboard.press('Tab')
    }
    assert.equal(keyboardFocused, true, 'profile option should be reachable through dialog keyboard navigation')
    const keyboardFocusStyle = await secondOption.evaluate((node) => {
      const style = getComputedStyle(node)
      return { focusVisible: node.matches(':focus-visible'), outlineStyle: style.outlineStyle, outlineWidth: Number.parseFloat(style.outlineWidth) }
    })
    assert.equal(keyboardFocusStyle.focusVisible, true, 'keyboard navigation should expose profile :focus-visible')
    assert.notEqual(keyboardFocusStyle.outlineStyle, 'none', 'keyboard-focused profile should show an outline')
    assert.ok(keyboardFocusStyle.outlineWidth >= 2, 'profile keyboard focus outline should be visible')
    await page.keyboard.press('Enter')
    await waitForProfileDashboard(page, {
      direction: '临床药学进阶',
      stage: '进阶',
      resources: '2 份',
      timeContains: '2026',
      recommendation: '继续阅读本轮学习资源',
    })
    await closeProfileDialog(page)
    const selectedDialog = await openProfileDialog(page)
    const selectedOption = selectedDialog.locator('.profile-option[data-learner-id="learner-2"]')
    assert.equal(await selectedOption.getAttribute('aria-pressed'), 'true', 'keyboard selection should mark the chosen option current')
    assert.equal((await selectedOption.locator('.profile-option-name').innerText()).trim(), '临床药学画像')
    const selected = await profileDashboardSnapshot(page)
    assert.deepEqual(selected.values.slice(0, 3), ['临床药学进阶', '进阶', '2 份'])
    assert.ok(selected.values[3].includes('2026'), 'recent learning time should update with the selected profile')
    assert.equal(selected.primaryDisabled, false)
    assert.equal(selected.currentLearnerId, 'learner-2')
    assert.equal(selected.directionId, 'kb-2')
    assert.equal(selected.directionName, '临床药学进阶')
    assert.equal(selected.currentProfile, 'learner-2')

    await selectedDialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(page)
    const afterCancel = await profileDashboardSnapshot(page)
    assert.deepEqual(afterCancel.values, selected.values, 'closing after selection should preserve the selected profile')
    assert.equal(afterCancel.currentLearnerId, 'learner-2')

    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForDashboard(page)
    const restored = await profileDashboardSnapshot(page)
    assert.deepEqual(restored.values, selected.values, 'profile selection should restore after reload')
    assert.equal(restored.currentLearnerId, 'learner-2')
    const restoredDialog = await openProfileDialog(page)
    assert.equal(await restoredDialog.locator('.profile-option[data-learner-id="learner-2"]').getAttribute('aria-pressed'), 'true')
    await page.keyboard.press('Escape')
    await closeProfileDialog(page)
    await assertRouteClick(page, '.workbench-primary', '/resources', 'profile switch recommendation')
    state.evidence.profilePickerChecks.push({
      scenario: 'multiple-profiles',
      keyboardSelection: 'learner-2',
      summaryValues: selected.values,
      recommendation: selected.recommendation,
      persistedLearnerId: restored.currentLearnerId,
      cancelCloseEscapePreserveState: true,
    })
  } finally {
    await page.close()
  }
}

async function testProfilePickerLoadingAndRetry(browser, base) {
  const loadingPage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-loading')
  try {
    await loadingPage.waitForFunction(() => document.querySelector('.home-hero')?.getAttribute('aria-busy') === 'true')
    assert.equal(await loadingPage.locator('.workspace-switch').isDisabled(), true, 'profile switch trigger should disable during directory loading')
    await waitForDashboard(loadingPage)
    assert.equal(await loadingPage.locator('.workspace-switch').isDisabled(), false, 'profile switch trigger should re-enable after directory loading')
    const dialog = await openProfileDialog(loadingPage)
    await dialog.locator('.profile-option').first().waitFor({ state: 'visible' })
    assert.equal(await dialog.locator('.profile-option').count(), 3)
    await dialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(loadingPage)
    state.evidence.profilePickerChecks.push({ scenario: 'directory-loading', switchDisabledWhileLoading: true, enabledAfterLoad: true })
  } finally {
    await loadingPage.close()
  }

  const failurePage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-failure')
  try {
    await waitForDashboard(failurePage)
    const dialog = await openProfileDialog(failurePage)
    await dialog.locator('.profile-switch-error').waitFor({ state: 'visible' })
    const beforeRetryRequests = state.requests.length
    const retry = dialog.locator('.profile-switch-retry')
    await retry.click()
    await waitForDashboard(failurePage)
    await dialog.locator('.profile-option').first().waitFor({ state: 'visible' })
    await dialog.locator('.profile-switch-error').waitFor({ state: 'hidden' })
    assert.equal(await dialog.locator('.profile-option').count(), 3, 'retry should restore the full profile directory')
    const retryRequests = profileRequestPages(state.requests.slice(beforeRetryRequests))
    assert.ok(retryRequests.length >= 1, 'retry should make another profile-directory GET request')
    const allAttempts = profileRequestPages(state.requests.filter((request) => request.scenario === 'profile-switch-failure'))
    assert.ok(allAttempts.length >= 2, 'failed directory load and retry should make separate GET requests')
    await dialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(failurePage)
    state.evidence.profilePickerChecks.push({ scenario: 'directory-error-retry', attempts: allAttempts.length, errorShown: true, retryRecovered: true })
  } finally {
    await failurePage.close()
  }
}

async function testProfilePickerPaginationAndMobileScroll(browser, base) {
  const page = await newFixturePage(browser, base, { width: 390, height: 844 }, 'profile-switch-paginated')
  try {
    await waitForDashboard(page)
    const dialog = await openProfileDialog(page)
    await page.waitForFunction(() => document.querySelectorAll('.profile-option').length === 53)
    assert.equal(await dialog.locator('.profile-option').count(), 53, 'profile directory should load all items beyond page 1')
    const pages = profileRequestPages(state.requests.filter((request) => request.scenario === 'profile-switch-paginated'))
    assert.ok(pages.some((request) => request.page === 1 && request.pageSize === 50), 'directory should request the first 50 profiles')
    assert.ok(pages.some((request) => request.page === 2 && request.pageSize === 50), 'directory should request the next page through total')

    const list = dialog.locator('.profile-options')
    const initial = await page.evaluate(() => {
      const content = document.querySelector('.content-area')
      return {
        contentScrollTop: content?.scrollTop ?? null,
        windowScrollY: window.scrollY,
        documentScrollTop: document.documentElement.scrollTop,
      }
    })
    const listGeometry = await list.evaluate((node) => ({ clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowY: getComputedStyle(node).overflowY }))
    assert.ok(listGeometry.scrollHeight > listGeometry.clientHeight + 1, 'long mobile profile list should scroll inside the dialog')
    assert.ok(['auto', 'scroll'].includes(listGeometry.overflowY), 'long mobile profile list should expose its own scroll container')
    const listBox = await list.boundingBox()
    assert.ok(listBox, 'profile list should have a visible mobile viewport')
    await page.mouse.move(listBox.x + listBox.width / 2, listBox.y + Math.min(listBox.height / 2, 120))
    await page.mouse.wheel(0, 650)
    await page.waitForFunction(() => (document.querySelector('.profile-options')?.scrollTop || 0) > 0)
    const afterWheel = await page.evaluate(() => {
      const content = document.querySelector('.content-area')
      const listNode = document.querySelector('.profile-options')
      return {
        listScrollTop: listNode?.scrollTop ?? 0,
        contentScrollTop: content?.scrollTop ?? null,
        windowScrollY: window.scrollY,
        documentScrollTop: document.documentElement.scrollTop,
      }
    })
    assert.ok(afterWheel.listScrollTop > 0, 'wheel input should scroll the profile list')
    assert.deepEqual({
      contentScrollTop: afterWheel.contentScrollTop,
      windowScrollY: afterWheel.windowScrollY,
      documentScrollTop: afterWheel.documentScrollTop,
    }, initial, 'scrolling the profile list should not move the dashboard behind the dialog')

    const lastOption = dialog.locator('.profile-option[data-learner-id="learner-53"]')
    await lastOption.scrollIntoViewIfNeeded()
    const lastBounds = await lastOption.evaluate((node) => {
      const rect = node.getBoundingClientRect()
      const listRect = node.closest('.profile-options').getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, listTop: listRect.top, listBottom: listRect.bottom, text: node.innerText.trim() }
    })
    assert.ok(lastBounds.text.includes('验收画像 53'), 'the item on the final page should be readable')
    assert.ok(lastBounds.top >= lastBounds.listTop - 1 && lastBounds.bottom <= lastBounds.listBottom + 1,
      'the final profile should be reachable inside the list viewport')
    const dialogBounds = await dialog.boundingBox()
    assert.ok(dialogBounds && dialogBounds.y >= -1 && dialogBounds.y + dialogBounds.height <= 845,
      'profile dialog should fit the mobile viewport')
    await dialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(page)
    state.evidence.profilePickerChecks.push({ scenario: 'paginated-mobile-list', optionCount: 53, pages, listGeometry, afterWheel, lastBounds, dialogBounds })
  } finally {
    await page.close()
  }
}

async function testProfilePickerRequestRace(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'profile-switch-race')
  try {
    await waitForDashboard(page)
    const firstDialog = await openProfileDialog(page)
    const optionTwo = firstDialog.locator('.profile-option[data-learner-id="learner-2"]')
    const requestStart = state.requests.length
    state.delayedResourceLearnerId = 'learner-2'
    state.delayedResourceMs = 900
    await optionTwo.click()
    await closeProfileDialog(page)
    await waitForFixture(() => state.requests.slice(requestStart).some((request) => request.path === '/api/resources/learner-2'),
      'slow profile resource request should start')
    const pending = await profileDashboardSnapshot(page)
    assert.equal(pending.heroBusy, 'true', 'hero should report loading while a selected profile is loading')
    assert.equal(pending.primaryDisabled, true, 'primary recommendation should be disabled while profile resources load')
    assert.equal(await page.locator('.workspace-switch').isDisabled(), false, 'profile switching should remain enabled while resources load')

    const secondDialog = await openProfileDialog(page)
    const optionThree = secondDialog.locator('.profile-option[data-learner-id="learner-3"]')
    await optionThree.click()
    await waitForProfileDashboard(page, {
      direction: '急救护理中级',
      stage: '中级',
      resources: '3 份',
      timeContains: '2026',
      recommendation: '继续阅读本轮学习资源',
    })
    await closeProfileDialog(page)
    await waitForFixture(() => state.delayedResponses.includes('resource:learner-2'),
      'older profile resource response should return after the newer selection')
    await page.waitForTimeout(100)
    const latest = await profileDashboardSnapshot(page)
    assert.equal(latest.currentLearnerId, 'learner-3', 'late response must not replace the latest selected profile')
    assert.deepEqual(latest.values.slice(0, 3), ['急救护理中级', '中级', '3 份'], 'late response must not overwrite the newest summary')
    assert.equal(latest.recommendation, '继续阅读本轮学习资源', 'late response must not replace the newest recommendation')
    assert.equal(latest.primaryDisabled, false, 'primary recommendation should re-enable after the latest profile finishes loading')

    const latestDialog = await openProfileDialog(page)
    assert.equal(await latestDialog.locator('.profile-option[data-learner-id="learner-3"]').getAttribute('aria-pressed'), 'true')
    await latestDialog.locator('.profile-switch-cancel').click()
    await closeProfileDialog(page)
    state.evidence.profilePickerChecks.push({
      scenario: 'rapid-switch-request-race',
      pendingProfile: pending.currentLearnerId,
      pendingHeroBusy: pending.heroBusy,
      pendingPrimaryDisabled: pending.primaryDisabled,
      lateResponse: state.delayedResponses.includes('resource:learner-2'),
      finalProfile: latest.currentLearnerId,
      finalSummary: latest.values,
      finalRecommendation: latest.recommendation,
    })
  } finally {
    await page.close()
  }
}

async function testProfileAndWorkbenchAlignment(browser, base) {
  for (const collapsed of [false, true]) {
    const page = await newFixturePage(browser, base, { width: 1331, height: 871 }, 'profile-switch-alignment')
    try {
      await waitForDashboard(page)
      if (collapsed) await page.locator('.sidebar-toggle').click()
      await waitForSidebarState(page, collapsed)
      const metrics = await page.evaluate(() => {
        const rect = (node) => {
          if (!node) return null
          const value = node.getBoundingClientRect()
          return { top: value.top, bottom: value.bottom, height: value.height }
        }
        const icons = [...document.querySelectorAll('.summary-icon')].map((node) => {
          const value = node.getBoundingClientRect()
          return value.top + value.height / 2
        })
        const values = [...document.querySelectorAll('.summary-value')].map(rect)
        const headings = [
          rect(document.querySelector('.learning-tools .section-heading')),
          rect(document.querySelector('.learning-route-panel .section-heading')),
        ]
        const bodies = [rect(document.querySelector('.tool-grid')), rect(document.querySelector('.route-list'))]
        return {
          viewport: { width: innerWidth, height: innerHeight },
          fit: document.querySelector('.home-page')?.classList.contains('is-fit-layout') || false,
          collapsed: document.querySelector('.app-shell')?.classList.contains('is-sidebar-collapsed') || false,
          icons,
          values,
          headings,
          bodies,
          separators: {
            toolTop: getComputedStyle(document.querySelector('.tool-grid')).borderTopWidth,
            lastToolBottom: getComputedStyle(document.querySelector('.tool-card:last-child')).borderBottomWidth,
            routeTop: getComputedStyle(document.querySelector('.route-list')).borderTopWidth,
            routeBottom: getComputedStyle(document.querySelector('.route-list')).borderBottomWidth,
          },
        }
      })
      const spread = (values) => Math.max(...values) - Math.min(...values)
      assert.equal(metrics.fit, true, '1331x871 alignment view should use measured one-screen layout')
      assert.equal(metrics.collapsed, collapsed)
      assert.equal(metrics.icons.length, 4)
      assert.ok(spread(metrics.icons) <= 1, 'all four summary icon centers should align within 1px: ' + JSON.stringify(metrics.icons))
      assert.equal(metrics.values.length, 4)
      assert.ok(metrics.headings.every(Boolean) && metrics.bodies.every(Boolean), 'both aligned sections should be present')
      assert.ok(spread(metrics.values.map((value) => value.bottom)) <= 1, 'summary value rows should share a bottom edge within 1px: ' + JSON.stringify(metrics.values))
      assert.ok(spread(metrics.values.map((value) => value.height)) <= 1, 'summary value rows should have a consistent height within 1px: ' + JSON.stringify(metrics.values))
      assert.ok(spread(metrics.headings.map((value) => value.top)) <= 1 && spread(metrics.headings.map((value) => value.bottom)) <= 1,
        'left and right section headings should share top and bottom edges within 1px: ' + JSON.stringify(metrics.headings))
      assert.ok(spread(metrics.bodies.map((value) => value.top)) <= 1 && spread(metrics.bodies.map((value) => value.bottom)) <= 1,
        'tool grid and learning loop should share top and bottom edges within 1px: ' + JSON.stringify(metrics.bodies))
      assert.ok(Number.parseFloat(metrics.separators.toolTop) >= 1 && Number.parseFloat(metrics.separators.lastToolBottom) >= 1
        && Number.parseFloat(metrics.separators.routeTop) >= 1 && Number.parseFloat(metrics.separators.routeBottom) >= 1,
      'aligned content bodies should retain their top and bottom separators: ' + JSON.stringify(metrics.separators))
      state.evidence.profileAlignmentChecks.push({ state: collapsed ? 'collapsed' : 'expanded', ...metrics })
    } finally {
      await page.close()
    }
  }
}

async function sidebarLayoutSnapshot(page) {
  return page.evaluate(() => {
    const shell = document.querySelector('.app-shell')
    const sidebar = document.querySelector('.sidebar')
    const inner = sidebar?.querySelector('.sidebar-inner')
    const main = document.querySelector('.main-area')
    const nav = [...document.querySelectorAll('.nav-list .nav-item')]
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height }
    }
    const style = (node) => node ? getComputedStyle(node) : null
    const outer = rect(sidebar)
    const clipPath = style(sidebar)?.clipPath || 'none'
    let clipWidth = outer?.width ?? null
    const clipMatch = clipPath.match(/^inset\((.*)\)$/)
    if (clipMatch && outer) {
      const content = clipMatch[1].split(/\s+round\b/)[0]
      const tokens = content.match(/calc\([^)]*\)|[^\s]+/g) || []
      const values = tokens.length === 1 ? [tokens[0], tokens[0], tokens[0], tokens[0]]
        : tokens.length === 2 ? [tokens[0], tokens[1], tokens[0], tokens[1]]
          : tokens.length === 3 ? [tokens[0], tokens[1], tokens[2], tokens[1]] : tokens
      const resolve = (token, reference) => {
        if (!token || token === '0' || token === '0px') return 0
        const calc = token.match(/^calc\(\s*([\d.]+)%\s*-\s*([\d.]+)px\s*\)$/)
        if (calc) return reference * Number(calc[1]) / 100 - Number(calc[2])
        const calcPixels = token.match(/^calc\(\s*([\d.]+)px\s*-\s*([\d.]+)px\s*\)$/)
        if (calcPixels) return Number(calcPixels[1]) - Number(calcPixels[2])
        if (token.endsWith('%')) return reference * Number.parseFloat(token) / 100
        return Number.parseFloat(token) || 0
      }
      const leftInset = resolve(values[3], outer.width)
      const rightInset = resolve(values[1], outer.width)
      clipWidth = outer.width - leftInset - rightInset
    }
    const nonActiveNav = nav.find((node) => !node.classList.contains('is-active')) || nav[0]
    const shellStyle = style(sidebar)
    const innerStyle = style(inner)
    const brand = document.querySelector('.brand-block')
    const brandName = document.querySelector('.brand-name')
    const navList = document.querySelector('.nav-list')
    const navStyle = style(navList)
    const nonActiveStyle = style(nonActiveNav)
    const context = document.querySelector('.context-panel')
    const contextStyle = style(context)
    const toggle = document.querySelector('.sidebar-toggle')
    const toggleStyle = style(toggle)
    const logout = document.querySelector('.logout-button')
    const logoutStyle = style(logout)
    const mainStyle = style(main)
    return {
      pathname: location.pathname,
      viewport: { width: innerWidth, height: innerHeight },
      collapsed: Boolean(shell?.classList.contains('is-sidebar-collapsed')),
      animating: Boolean(shell?.classList.contains('is-sidebar-animating')),
      resizeObserverCallbacks: window.__dashboardResizeObserverCallbacks || 0,
      sidebarRect: outer,
      clipPath,
      visibleClipWidth: clipWidth,
      sidebarBackground: shellStyle?.backgroundColor || '',
      innerRect: rect(inner),
      brand: {
        rect: rect(brand),
        name: brandName?.textContent.trim() || '',
        imageAlt: document.querySelector('.brand-logo')?.getAttribute('alt') || '',
        imageLoaded: Boolean(document.querySelector('.brand-logo')?.naturalWidth),
        nameColor: style(brandName)?.color || '',
        nameSize: style(brandName)?.fontSize || '',
        innerDisplay: innerStyle?.display || '',
      },
      navList: {
        rect: rect(navList),
        display: navStyle?.display || '',
        gridTemplateRows: navStyle?.gridTemplateRows || '',
        gridTemplateColumns: navStyle?.gridTemplateColumns || '',
        gap: navStyle?.gap || '',
        items: nav.map((node) => {
          const box = rect(node)
          const icon = node.querySelector('.nav-icon')
          const iconStyle = style(icon)
          return {
            label: node.getAttribute('aria-label') || '',
            href: node.getAttribute('href') || '',
            active: node.classList.contains('is-active'),
            rect: box,
            centerY: box ? box.top + box.height / 2 : null,
            color: style(node)?.color || '',
            fontSize: style(node.querySelector('.nav-text'))?.fontSize || '',
            icon: rect(icon),
            iconTransform: iconStyle?.transform || 'none',
          }
        }),
        commonItem: nonActiveNav ? {
          color: nonActiveStyle?.color || '',
          borderRadius: nonActiveStyle?.borderRadius || '',
          fontSize: style(nonActiveNav.querySelector('.nav-text'))?.fontSize || '',
          minHeight: nonActiveStyle?.minHeight || '',
        } : null,
      },
      context: {
        rect: rect(context),
        background: contextStyle?.backgroundColor || '',
        borderTopColor: contextStyle?.borderTopColor || '',
        inert: Boolean(context?.inert),
        ariaHidden: context?.getAttribute('aria-hidden'),
      },
      toggle: {
        rect: rect(toggle),
        color: toggleStyle?.color || '',
        background: toggleStyle?.backgroundColor || '',
        borderRadius: toggleStyle?.borderRadius || '',
        expanded: toggle?.getAttribute('aria-expanded') || '',
        label: toggle?.getAttribute('aria-label') || '',
      },
      logout: {
        rect: rect(logout),
        color: logoutStyle?.color || '',
        background: logoutStyle?.backgroundColor || '',
        borderRadius: logoutStyle?.borderRadius || '',
        label: logout?.getAttribute('aria-label') || '',
      },
      main: {
        rect: rect(main),
        clientWidth: main?.clientWidth ?? null,
        transform: mainStyle?.transform || 'none',
      },
    }
  })
}

async function beginSidebarAnimationSampling(page) {
  await page.evaluate(() => {
    const shell = document.querySelector('.app-shell')
    const sidebar = document.querySelector('.sidebar')
    const main = document.querySelector('.main-area')
    const nav = [...document.querySelectorAll('.nav-list .nav-item')]
    const icons = nav.map((node) => node.querySelector('.nav-icon'))
    const textNodes = nav.map((node) => node.querySelector('.nav-text'))
    window.__dashboardSidebarMotionSamples = []
    window.__dashboardSidebarMotionDone = false
    window.__dashboardSidebarMotionTargets = { shell, sidebar, main, nav }
    const startedAt = performance.now()
    let observedMotion = false
    let idleFrames = 0
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height }
    }
    const scale = (node) => {
      if (!node) return null
      const transform = getComputedStyle(node).transform
      const matrix = new DOMMatrixReadOnly(transform === 'none' ? 'matrix(1, 0, 0, 1, 0, 0)' : transform)
      return { x: matrix.a, y: matrix.d, transform }
    }
    const sample = () => {
      if (!shell || !sidebar || !main) {
        window.__dashboardSidebarMotionDone = true
        return
      }
      const mainAnimations = main.getAnimations().filter((animation) => animation.playState === 'running' || animation.playState === 'pending')
      const animating = shell.classList.contains('is-sidebar-animating')
      const running = animating && mainAnimations.length > 0
      if (running) {
        observedMotion = true
        idleFrames = 0
      } else if (observedMotion && !animating) {
        idleFrames += 1
      } else if (animating) {
        idleFrames = 0
      }
      if (observedMotion) {
        window.__dashboardSidebarMotionSamples.push({
          time: performance.now(),
          animating: shell.classList.contains('is-sidebar-animating'),
          running,
          collapsed: shell.classList.contains('is-sidebar-collapsed'),
          main: { ...rect(main), clientWidth: main.clientWidth, transform: getComputedStyle(main).transform, animationCount: mainAnimations.length },
          sidebar: { ...rect(sidebar), clipPath: getComputedStyle(sidebar).clipPath },
          nav: nav.map((node) => ({ ...rect(node), centerY: rect(node).top + rect(node).height / 2, width: rect(node).width, height: rect(node).height })),
          iconSizes: icons.map((node) => {
            const box = rect(node)
            return box ? { width: box.width, height: box.height } : null
          }),
          textScale: textNodes.map(scale),
          resizeObserverCallbacks: window.__dashboardResizeObserverCallbacks || 0,
        })
      }
      if (observedMotion && !animating && idleFrames >= 4) {
        window.__dashboardSidebarMotionDone = true
        return
      }
      if (performance.now() - startedAt > 2200) {
        window.__dashboardSidebarMotionDone = true
        return
      }
      requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
}

function sidebarSpacingSpread(items) {
  const centers = items.map((item) => item.centerY)
  const gaps = centers.slice(1).map((value, index) => value - centers[index])
  return gaps.length ? Math.max(...gaps) - Math.min(...gaps) : Infinity
}

function assertSidebarMotion(start, samples, end, expectedCollapsed, label) {
  const active = samples.filter((sample) => sample.running)
  assert.ok(active.length >= 4, label + ': expected several real intermediate WAAPI frames, got ' + active.length)
  assert.equal(end.animating, false, label + ': animation marker should clear at rest')
  assert.equal(end.collapsed, expectedCollapsed, label + ': final collapsed state is wrong')
  assert.equal(end.main.transform, 'none', label + ': main-area transform should be cleared at rest')
  assert.equal(end.context.inert, expectedCollapsed, label + ': collapsed context inert state is wrong')
  assert.equal(end.context.ariaHidden, String(expectedCollapsed), label + ': collapsed context aria-hidden state is wrong')
  assert.ok(Math.abs(end.visibleClipWidth - (expectedCollapsed ? 72 : end.sidebarRect.width)) <= 1,
    label + ': computed sidebar clip should show ' + (expectedCollapsed ? '72px' : 'the full sidebar') + ', got ' + end.visibleClipWidth)
  assert.ok(Math.abs(end.navList.items[0].rect.width - (expectedCollapsed ? 52 : end.sidebarRect.width - 20)) <= 2,
    label + ': navigation link should use the final clickable width')
  assert.ok(sidebarSpacingSpread(end.navList.items) <= 1, label + ': five navigation centers should be equally spaced')
  assert.ok(sidebarSpacingSpread(start.navList.items) <= 1, label + ': starting navigation centers should be equally spaced')
  assert.ok(active.every((sample) => sample.animating), label + ': every captured intermediate frame should be marked as animating')
  const startLeft = start.main.rect.left
  const endLeft = end.main.rect.left
  const totalMovement = endLeft - startLeft
  assert.ok(Math.abs(totalMovement) >= 50, label + ': main content should visibly move between sidebar states')
  const path = [startLeft, ...active.map((sample) => sample.main.left), endLeft]
  const direction = Math.sign(totalMovement)
  const deltas = path.slice(1).map((value, index) => (value - path[index]) * direction)
  assert.ok(deltas.every((delta) => delta >= -1), label + ': main content position should move continuously toward the destination')
  assert.ok(Math.max(...deltas) < Math.abs(totalMovement) * 0.6,
    label + ': a single frame must not jump across most of the transition')
  const finalWidths = active.slice(1).map((sample) => sample.main.clientWidth)
  assert.ok(finalWidths.length && finalWidths.every((width) => width === end.main.clientWidth),
    label + ': main grid width should settle once before transform interpolation')
  const clipValues = [start.visibleClipWidth, ...active.map((sample) => {
    const width = sample.sidebar.width
    const clip = sample.sidebar.clipPath.match(/^inset\((.*)\)$/)
    if (!clip) return width
    const tokens = clip[1].split(/\s+round\b/)[0].match(/calc\([^)]*\)|[^\s]+/g) || []
    const values = tokens.length === 1 ? [tokens[0], tokens[0], tokens[0], tokens[0]]
      : tokens.length === 2 ? [tokens[0], tokens[1], tokens[0], tokens[1]]
        : tokens.length === 3 ? [tokens[0], tokens[1], tokens[2], tokens[1]] : tokens
    const resolve = (token) => {
      if (!token || token === '0' || token === '0px') return 0
      const match = token.match(/^([\d.]+)px$/)
      return match ? Number(match[1]) : Number.parseFloat(token) || 0
    }
    return width - resolve(values[1]) - resolve(values[3])
  }), end.visibleClipWidth]
  assert.ok(new Set(clipValues.map((value) => Math.round(value * 10) / 10)).size >= 3,
    label + ': sidebar clipping should have real intermediate geometry')
  const clipMovement = clipValues.at(-1) - clipValues[0]
  const clipDirection = Math.sign(clipMovement)
  const clipDeltas = clipValues.slice(1).map((value, index) => (value - clipValues[index]) * clipDirection)
  assert.ok(Math.abs(clipMovement) >= 50 && clipDeltas.every((delta) => delta >= -1),
    label + ': sidebar clip should move continuously toward its final visible width')
  assert.ok(Math.max(...clipDeltas) < Math.abs(clipMovement) * 0.6,
    label + ': a single clip frame must not jump across most of the transition')
  const navCenterPaths = start.navList.items.map((item, index) => [
    item.centerY,
    ...active.map((sample) => sample.nav[index].centerY),
    end.navList.items[index].centerY,
  ])
  const navCenterDeltas = navCenterPaths.map((path) => {
    const movement = path.at(-1) - path[0]
    const direction = Math.sign(movement)
    const deltas = path.slice(1).map((value, index) => (value - path[index]) * direction)
    return { movement, deltas }
  })
  assert.ok(navCenterDeltas.some((item) => Math.abs(item.movement) > 1), label + ': navigation rows should animate to the destination grid positions')
  for (const item of navCenterDeltas.filter((item) => Math.abs(item.movement) > 1)) {
    assert.ok(item.deltas.every((delta) => delta >= -1), label + ': navigation row positions should not reverse mid-transition')
    assert.ok(Math.max(...item.deltas) < Math.abs(item.movement) * 0.6,
      label + ': a navigation row should not jump directly to its final vertical position')
  }
  const sizes = [start, ...active.map((sample) => ({ navList: { items: sample.nav.map((item, index) => ({ icon: sample.iconSizes[index] })) } })), end]
    .flatMap((snapshot) => snapshot.navList.items.map((item) => item.icon))
    .filter(Boolean)
  assert.ok(sizes.every((size) => Math.abs(size.width - sizes[0].width) <= 1 && Math.abs(size.height - sizes[0].height) <= 1),
    label + ': sidebar icon dimensions must not scale during animation')
  const scales = active.flatMap((sample) => sample.textScale).filter(Boolean)
  assert.ok(scales.every((item) => Math.abs(item.x - 1) <= 0.01 && Math.abs(item.y - 1) <= 0.01),
    label + ': navigation text must move without scaling')
  const frameDeltas = active.slice(1).map((sample, index) => sample.time - active[index].time)
  return {
    label,
    direction: expectedCollapsed ? 'collapse' : 'expand',
    startLeft,
    endLeft,
    totalMovement,
    frameCount: active.length,
    frameDeltasMs: frameDeltas,
    maxFrameDeltaMs: frameDeltas.length ? Math.max(...frameDeltas) : 0,
    resizeObserverCallbacks: { start: start.resizeObserverCallbacks, during: active.at(-1).resizeObserverCallbacks, end: end.resizeObserverCallbacks },
    startClipWidth: start.visibleClipWidth,
    endClipWidth: end.visibleClipWidth,
    navCenterMovement: navCenterDeltas.map((item) => item.movement),
    mainClientWidth: { start: start.main.clientWidth, animated: active.map((sample) => sample.main.clientWidth), end: end.main.clientWidth },
    iconSize: sizes[0],
    navGaps: {
      start: start.navList.items.slice(1).map((item, index) => item.centerY - start.navList.items[index].centerY),
      end: end.navList.items.slice(1).map((item, index) => item.centerY - end.navList.items[index].centerY),
    },
    samples,
  }
}

async function waitForSidebarState(page, expectedCollapsed) {
  await page.waitForFunction((expected) => {
    const shell = document.querySelector('.app-shell')
    return shell?.classList.contains('is-sidebar-collapsed') === expected
      && !shell.classList.contains('is-sidebar-animating')
  }, expectedCollapsed)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function captureSidebarMidframe(page, label, expectedCollapsed) {
  await page.waitForFunction((expected) => {
    const shell = document.querySelector('.app-shell')
    const main = document.querySelector('.main-area')
    const animation = main?.getAnimations().find((item) =>
      (item.playState === 'running' || item.playState === 'pending')
      && (item.effect?.getKeyframes() || []).some((frame) => 'transform' in frame))
    const duration = Number(animation?.effect?.getTiming().duration)
    const progress = Number(animation?.currentTime) / duration
    return shell?.classList.contains('is-sidebar-animating') === true
      && shell.classList.contains('is-sidebar-collapsed') === expected
      && Number.isFinite(progress) && progress >= 0.35 && progress <= 0.55
  }, expectedCollapsed, { timeout: 2000 })

  const frame = await page.evaluate((expected) => {
    const shell = document.querySelector('.app-shell')
    const sidebar = document.querySelector('.sidebar')
    const main = document.querySelector('.main-area')
    const nav = [...document.querySelectorAll('.nav-list .nav-item')]
    const isMotion = (animation) => (animation.effect?.getKeyframes() || []).some((keyframe) =>
      ['transform', 'clipPath', 'clip-path'].some((property) => property in keyframe))
    const animations = [...new Set([main, sidebar, ...nav].filter(Boolean).flatMap((node) => node.getAnimations()))]
      .filter((animation) => isMotion(animation)
        && (animation.playState === 'running' || animation.playState === 'pending'))
    const mainAnimation = animations.find((animation) => animation.effect?.target === main
      && (animation.effect?.getKeyframes() || []).some((keyframe) => 'transform' in keyframe))
    const duration = Number(mainAnimation?.effect?.getTiming().duration)
    const currentTime = Number(mainAnimation?.currentTime)
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height }
    }
    const logo = document.querySelector('.brand-logo')
    const logoutIcon = document.querySelector('.logout-icon svg')
    const visible = (node) => {
      if (!node) return false
      const style = getComputedStyle(node)
      const box = rect(node)
      return Boolean(box && box.width > 0 && box.height > 0 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity) > 0)
    }
    window.__dashboardPausedSidebarAnimations = animations
    animations.forEach((animation) => animation.pause())
    return {
      expectedCollapsed: expected,
      collapsed: Boolean(shell?.classList.contains('is-sidebar-collapsed')),
      animating: Boolean(shell?.classList.contains('is-sidebar-animating')),
      viewport: { width: innerWidth, height: innerHeight },
      timelineProgress: duration > 0 ? currentTime / duration : null,
      animationCount: animations.length,
      main: rect(main),
      sidebar: rect(sidebar),
      navCenters: nav.map((node) => {
        const box = rect(node)
        return box ? box.top + box.height / 2 : null
      }),
      logo: { loaded: Boolean(logo?.naturalWidth), visible: visible(logo), rect: rect(logo) },
      logoutSvg: { visible: visible(logoutIcon), rect: rect(logoutIcon) },
    }
  }, expectedCollapsed)
  const layout = await sidebarLayoutSnapshot(page)
  const filename = 'sidebar-motion-' + label + '-mid.png'
  let screenshot
  try {
    assert.equal(frame.animating, true, label + ': midpoint screenshot must be captured during the real sidebar transition')
    assert.equal(frame.collapsed, expectedCollapsed, label + ': midpoint target state is incorrect')
    assert.ok(frame.timelineProgress >= 0.3 && frame.timelineProgress <= 0.7,
      label + ': screenshot should record a naturally reached middle animation progress: ' + frame.timelineProgress)
    assert.ok(layout.visibleClipWidth > 73 && layout.visibleClipWidth < 223,
      label + ': screenshot should show a nonterminal sidebar clip width: ' + layout.visibleClipWidth)
    assert.ok(frame.animationCount >= 6, label + ': main/sidebar/navigation WAAPI motions should all be paused for the frame')
    assert.equal(frame.logo.loaded, true, label + ': logo image should be loaded in the midpoint screenshot')
    assert.equal(frame.logo.visible, true, label + ': logo should be visibly painted in the midpoint screenshot')
    assert.equal(frame.logoutSvg.visible, true, label + ': logout SVG should be visibly painted in the midpoint screenshot')
    assert.ok(frame.main && frame.sidebar && frame.navCenters.length === 5, label + ': midpoint geometry should be recorded')
    screenshot = await page.screenshot({ path: path.join(reportDir, filename) })
  } finally {
    await page.evaluate(() => {
      const animations = window.__dashboardPausedSidebarAnimations || []
      animations.forEach((animation) => animation.play())
      delete window.__dashboardPausedSidebarAnimations
    })
  }
  const evidence = {
    label,
    filename,
    captureType: 'paused-snapshot-after-natural-progress',
    includedInMotionDiagnosis: false,
    width: screenshot.readUInt32BE(16),
    height: screenshot.readUInt32BE(20),
    viewport: frame.viewport,
    timelineProgress: frame.timelineProgress,
    capturedWhileAnimating: frame.animating,
    targetCollapsed: frame.collapsed,
    visibleClipWidth: layout.visibleClipWidth,
    main: frame.main,
    sidebar: frame.sidebar,
    navCenters: frame.navCenters,
    logo: frame.logo,
    logoutSvg: frame.logoutSvg,
    pausedAnimationCount: frame.animationCount,
  }
  state.evidence.screenshots.push({ filename, width: evidence.width, height: evidence.height, viewport: evidence.viewport, phase: 'mid-transition', timelineProgress: evidence.timelineProgress })
  return evidence
}

async function assertSidebarRest(page, expectedCollapsed, label) {
  const snapshot = await sidebarLayoutSnapshot(page)
  const motion = await page.evaluate(() => {
    const shell = document.querySelector('.app-shell')
    const sidebar = document.querySelector('.sidebar')
    const main = document.querySelector('.main-area')
    const nav = [...document.querySelectorAll('.nav-list .nav-item')]
    const targets = [main, sidebar, ...nav].filter(Boolean)
    const allRunning = targets.flatMap((node) => node.getAnimations())
      .filter((animation) => animation.playState === 'running' || animation.playState === 'pending')
    const describe = (animation) => ({
      target: animation.effect?.target?.className || '',
      state: animation.playState,
      kind: animation.constructor.name,
      transitionProperty: animation.transitionProperty || '',
      properties: [...new Set(animation.effect?.getKeyframes().flatMap((frame) => Object.keys(frame)) || [])]
        .filter((property) => !['offset', 'easing', 'composite'].includes(property)),
    })
    const isSidebarMotion = (animation) => (animation.effect?.getKeyframes() || []).some((frame) =>
      ['transform', 'clipPath', 'clip-path'].some((property) => property in frame))
    return {
      animating: Boolean(shell?.classList.contains('is-sidebar-animating')),
      mainTransform: main ? getComputedStyle(main).transform : 'missing',
      sidebarTransform: sidebar ? getComputedStyle(sidebar).transform : 'missing',
      navTransforms: nav.map((node) => getComputedStyle(node).transform),
      running: allRunning.filter(isSidebarMotion).map(describe),
      incidentalTransitions: allRunning.filter((animation) => !isSidebarMotion(animation)).map(describe),
    }
  })
  assert.equal(snapshot.collapsed, expectedCollapsed, label + ': sidebar state did not settle')
  assert.equal(motion.animating, false, label + ': animation marker remains after cancellation/finish')
  assert.equal(motion.mainTransform, 'none', label + ': main-area has a residual transform')
  assert.equal(motion.sidebarTransform, 'none', label + ': sidebar has a residual transform')
  assert.ok(motion.navTransforms.every((transform) => transform === 'none'), label + ': navigation links have residual transforms')
  assert.deepEqual(motion.running, [], label + ': sidebar motion remains active after cancellation/finish')
  return { snapshot, motion }
}

async function sampleSidebarTransition(page, expectedCollapsed, label) {
  const start = await sidebarLayoutSnapshot(page)
  await beginSidebarAnimationSampling(page)
  await page.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
  await page.waitForFunction(() => window.__dashboardSidebarMotionDone === true)
  await waitForSidebarState(page, expectedCollapsed)
  const samples = await page.evaluate(() => window.__dashboardSidebarMotionSamples || [])
  const end = await sidebarLayoutSnapshot(page)
  const result = assertSidebarMotion(start, samples, end, expectedCollapsed, label)
  const rest = await assertSidebarRest(page, expectedCollapsed, label)
  return { ...result, final: rest.snapshot }
}

async function waitForSidebarTimelineProgress(page, expectedCollapsed, minimum, maximum) {
  await page.waitForFunction(({ expected, min, max }) => {
    const shell = document.querySelector('.app-shell')
    const main = document.querySelector('.main-area')
    const animation = main?.getAnimations().find((item) =>
      (item.playState === 'running' || item.playState === 'pending')
      && (item.effect?.getKeyframes() || []).some((frame) => 'transform' in frame))
    const duration = Number(animation?.effect?.getTiming().duration)
    const progress = Number(animation?.currentTime) / duration
    return shell?.classList.contains('is-sidebar-animating') === true
      && shell.classList.contains('is-sidebar-collapsed') === expected
      && Number.isFinite(progress) && progress >= min && progress <= max
  }, { expected: expectedCollapsed, min: minimum, max: maximum }, { timeout: 2000 })
}

async function sidebarStyleSignature(page) {
  return page.evaluate(() => {
    const computed = (node, properties) => {
      if (!node) return null
      const style = getComputedStyle(node)
      return Object.fromEntries(properties.map((name) => [name, style[name]]))
    }
    const sidebar = document.querySelector('.sidebar')
    const inner = sidebar?.querySelector('.sidebar-inner')
    const brand = document.querySelector('.brand-block')
    const name = document.querySelector('.brand-name')
    const navList = document.querySelector('.nav-list')
    const nonActive = [...document.querySelectorAll('.nav-item')].find((item) => !item.classList.contains('is-active'))
      || document.querySelector('.nav-item')
    const navText = nonActive?.querySelector('.nav-text')
    const context = document.querySelector('.context-panel')
    const toggle = document.querySelector('.sidebar-toggle')
    const logout = document.querySelector('.logout-button')
    return {
      sidebar: computed(sidebar, ['backgroundColor', 'color', 'width', 'clipPath']),
      inner: computed(inner, ['display', 'gridTemplateRows', 'gridTemplateColumns', 'gap', 'padding']),
      brand: computed(brand, ['display', 'gridTemplateColumns', 'gap', 'minHeight']),
      brandName: computed(name, ['color', 'fontSize', 'fontWeight', 'lineHeight']),
      navList: computed(navList, ['display', 'gridTemplateRows', 'gridTemplateColumns', 'alignContent', 'gap']),
      navItem: computed(nonActive, ['display', 'gridTemplateColumns', 'gridTemplateRows', 'color', 'backgroundColor', 'borderRadius', 'fontSize', 'minHeight', 'padding']),
      navText: computed(navText, ['fontSize', 'fontWeight', 'lineHeight', 'color']),
      context: computed(context, ['display', 'backgroundColor', 'borderTopColor', 'borderTopStyle', 'padding', 'margin']),
      toggle: computed(toggle, ['display', 'height', 'color', 'backgroundColor', 'borderRadius', 'borderColor']),
      logout: computed(logout, ['display', 'height', 'color', 'backgroundColor', 'borderRadius', 'borderColor']),
    }
  })
}

async function testSharedSidebarRoutesAndKeyboard(browser, base) {
  const routes = [
    { path: '/dashboard', title: '工作台', active: '/dashboard', key: 'dashboard' },
    { path: '/learning/new', title: '创建学习方向', active: '/learning/new', key: 'learning-new' },
    { path: '/generate', title: '资源生成', active: '/generate', key: 'generate' },
    { path: '/resources', title: '学习资源', active: '/resources', key: 'resources' },
    { path: '/feedback', title: '学习反馈', active: '/feedback', key: 'feedback' },
    { path: '/report', title: '学习报告', active: null, key: 'report' },
    { path: '/learning/history', title: '学习历史', active: null, key: 'history' },
    { path: '/user/profile', title: '用户资料', active: null, key: 'user-profile' },
  ]
  const page = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  let referenceStyles = null
  try {
    for (const route of routes) {
      await page.goto(base + route.path, { waitUntil: 'domcontentloaded' })
      await page.waitForFunction((pathName) => location.pathname === pathName, route.path)
      await page.locator('.app-shell .sidebar-inner').waitFor({ state: 'visible' })
      await page.waitForFunction((expectedTitle) => document.querySelector('.topbar h1')?.textContent.trim() === expectedTitle, route.title)
      const title = (await page.locator('.topbar h1').innerText()).trim()
      assert.equal(title, route.title, route.path + ': shell should retain the route-specific page title')
      assert.equal(await page.locator('.sidebar').count(), 1, route.path + ': shared sidebar is missing')
      assert.equal(await page.locator('.sidebar-inner').count(), 1, route.path + ': shared sidebar inner wrapper is missing')
      const signature = await sidebarStyleSignature(page)
      if (!referenceStyles) referenceStyles = signature
      else assert.deepEqual(signature, referenceStyles, route.path + ': shared sidebar visual styles diverged from dashboard')

      const snapshot = await sidebarLayoutSnapshot(page)
      assert.equal(snapshot.sidebarBackground.toLowerCase(), 'rgb(16, 35, 57)', route.path + ': sidebar background should be #102339')
      assert.ok(Math.abs(snapshot.sidebarRect.width - 224) <= 1, route.path + ': expanded sidebar outer width should remain fixed at 224px')
      assert.ok(Math.abs(snapshot.visibleClipWidth - snapshot.sidebarRect.width) <= 1, route.path + ': expanded sidebar should reveal its full width')
      assert.equal(snapshot.navList.items.length, 5, route.path + ': all five navigation entries should remain')
      assert.deepEqual(snapshot.navList.items.map((item) => item.href), ['/dashboard', '/learning/new', '/generate', '/resources', '/feedback'],
        route.path + ': sidebar navigation targets changed')
      assert.ok(snapshot.navList.items.every((item) => item.rect.width > 160 && item.rect.height > 0), route.path + ': expanded navigation links should use full clickable rows')
      assert.ok(snapshot.navList.items.every((item) => item.label), route.path + ': every navigation entry needs an accessible name')
      assert.ok(sidebarSpacingSpread(snapshot.navList.items) <= 1, route.path + ': five navigation centers should be equally spaced')
      assert.ok(Math.max(...snapshot.navList.items.map((item) => item.rect.height)) - Math.min(...snapshot.navList.items.map((item) => item.rect.height)) <= 1,
        route.path + ': navigation rows should have equal height')
      assert.equal(snapshot.navList.items.filter((item) => item.active).length, route.active ? 1 : 0,
        route.path + ': active navigation state should match the route')
      if (route.active) assert.equal(snapshot.navList.items.find((item) => item.active)?.href, route.active, route.path + ': wrong navigation item is active')
      assert.equal(snapshot.context.inert, false, route.path + ': expanded learning context should remain interactive')
      assert.equal(snapshot.toggle.expanded, 'true', route.path + ': expanded state should be announced')
      assert.equal(snapshot.logout.label, '退出登录', route.path + ': logout action should remain accessible')

      const filename = 'sidebar-route-' + route.key + '-1393x871.png'
      const buffer = await page.screenshot({ path: path.join(reportDir, filename) })
      state.evidence.screenshots.push({ filename, width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20), viewport: { width: 1393, height: 871 } })
      state.evidence.sidebarRouteChecks.push({ route: route.path, title, styleSignature: signature, ...snapshot })
    }

    await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
    await waitForDashboard(page)
    const firstNav = page.locator('.nav-list .nav-item[href="/dashboard"]')
    await firstNav.focus()
    await page.keyboard.press('Tab')
    const secondNav = page.locator('.nav-list .nav-item[href="/learning/new"]')
    assert.equal(await secondNav.evaluate((node) => document.activeElement === node), true, 'Tab should advance through sidebar navigation')
    const focus = await secondNav.evaluate((node) => {
      const style = getComputedStyle(node)
      return { focusVisible: node.matches(':focus-visible'), outlineStyle: style.outlineStyle, outlineWidth: Number.parseFloat(style.outlineWidth) }
    })
    assert.equal(focus.focusVisible, true, 'keyboard navigation should show visible focus on the sidebar link')
    assert.notEqual(focus.outlineStyle, 'none', 'sidebar keyboard focus should include an outline')
    assert.ok(focus.outlineWidth >= 2, 'sidebar focus outline should be visible')
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => location.pathname === '/learning/new')
    await page.locator('.sidebar-toggle').focus()
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => document.querySelector('.app-shell')?.classList.contains('is-sidebar-collapsed') === true
      && !document.querySelector('.app-shell')?.classList.contains('is-sidebar-animating'))
    assert.equal(await page.evaluate(() => localStorage.getItem('app_sidebar_collapsed')), 'true', 'keyboard sidebar toggle should persist collapsed state')
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('.app-shell .sidebar-inner').waitFor({ state: 'visible' })
    await waitForSidebarState(page, true)
    const collapsed = await sidebarLayoutSnapshot(page)
    assert.equal(collapsed.toggle.expanded, 'false')
    assert.ok(Math.abs(collapsed.visibleClipWidth - 72) <= 1, 'collapsed sidebar should reveal the 72px navigation strip')
    assert.ok(collapsed.navList.items.every((item) => Math.abs(item.rect.width - 52) <= 1), 'collapsed navigation entries should retain 52px click targets')
    assert.equal(await page.evaluate(() => localStorage.getItem('app_sidebar_collapsed')), 'true')
    state.evidence.sidebarKeyboardChecks.push({ routeNavigation: '/learning/new', tabFocus: focus, enterNavigation: true, persistedCollapsed: collapsed })
  } finally {
    await page.close()
  }
}

async function waitForRunningSidebarAnimation(page) {
  await page.waitForFunction(() => {
    const shell = document.querySelector('.app-shell')
    const main = document.querySelector('.main-area')
    return shell?.classList.contains('is-sidebar-animating') === true
      && main?.getAnimations().some((animation) => animation.playState === 'running' || animation.playState === 'pending') === true
  })
}

async function testSidebarAnimationLifecycle(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke', { trackResizeObserver: true })
  try {
    await waitForDashboard(page)
    const collapse = await sampleSidebarTransition(page, true, 'normal-collapse')
    const expand = await sampleSidebarTransition(page, false, 'normal-expand')
    state.evidence.sidebarAnimationChecks.push(collapse, expand)

    const rapidStart = await sidebarLayoutSnapshot(page)
    await beginSidebarAnimationSampling(page)
    await page.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForRunningSidebarAnimation(page)
    for (let index = 0; index < 3; index += 1) {
      await page.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(true))))
    }
    await waitForSidebarState(page, false)
    const rapidSamples = await page.evaluate(() => window.__dashboardSidebarMotionSamples || [])
    const rapidRest = await assertSidebarRest(page, false, 'rapid-reversal')
    assert.ok(rapidSamples.some((sample) => sample.collapsed) && rapidSamples.some((sample) => !sample.collapsed),
      'rapid reversal should record both collapsed and expanded target states')
    state.evidence.sidebarAnimationChecks.push({
      label: 'rapid-reversal',
      clicksDuringMotion: 3,
      final: rapidRest.snapshot,
      activeFrames: rapidSamples.filter((sample) => sample.running).length,
      observedStates: [...new Set(rapidSamples.map((sample) => sample.collapsed))],
      resizeObserverCallbacks: rapidSamples.map((sample) => sample.resizeObserverCallbacks),
      start: rapidStart,
      samples: rapidSamples,
    })
  } finally {
    await page.close()
  }

  const reducedPage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(reducedPage)
    await beginSidebarAnimationSampling(reducedPage)
    await reducedPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForRunningSidebarAnimation(reducedPage)
    await reducedPage.emulateMedia({ reducedMotion: 'reduce' })
    await waitForSidebarState(reducedPage, true)
    const reducedCancel = await assertSidebarRest(reducedPage, true, 'reduced-motion-during-transition')
    await reducedPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForSidebarState(reducedPage, false)
    const reducedDirect = await assertSidebarRest(reducedPage, false, 'reduced-motion-direct-toggle')
    state.evidence.sidebarAnimationChecks.push({
      label: 'dynamic-reduced-motion',
      cancelledTo: reducedCancel.snapshot.collapsed,
      directToggleTo: reducedDirect.snapshot.collapsed,
      finalState: reducedDirect.snapshot,
    })
  } finally {
    await reducedPage.close()
  }

  const resizePage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(resizePage)
    await beginSidebarAnimationSampling(resizePage)
    await resizePage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForRunningSidebarAnimation(resizePage)
    await resizePage.setViewportSize({ width: 390, height: 844 })
    await waitForSidebarState(resizePage, true)
    const mobile = await assertSidebarRest(resizePage, true, 'resize-to-mobile')
    assert.equal(mobile.snapshot.clipPath, 'none', 'mobile navigation should not retain the desktop clip mask')
    await resizePage.setViewportSize({ width: 1393, height: 871 })
    await waitForSidebarState(resizePage, true)
    const restored = await assertSidebarRest(resizePage, true, 'resize-back-to-desktop')
    assert.ok(Math.abs(restored.snapshot.visibleClipWidth - 72) <= 1, 'desktop collapse state should restore its clipped 72px strip')
    state.evidence.sidebarAnimationChecks.push({ label: 'resize-cancellation', mobile: mobile.snapshot, restored: restored.snapshot })
  } finally {
    await resizePage.close()
  }

  const businessRoutePage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(businessRoutePage)
    await beginSidebarAnimationSampling(businessRoutePage)
    await businessRoutePage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForRunningSidebarAnimation(businessRoutePage)
    await businessRoutePage.evaluate(() => document.querySelector('.nav-item[href="/learning/new"]')?.click())
    await businessRoutePage.waitForFunction(() => location.pathname === '/learning/new')
    await waitForSidebarState(businessRoutePage, true)
    const routeCancel = await assertSidebarRest(businessRoutePage, true, 'business-route-cancellation')
    state.evidence.sidebarAnimationChecks.push({ label: 'business-route-cancellation', route: '/learning/new', final: routeCancel.snapshot })
  } finally {
    await businessRoutePage.close()
  }

  const publicRoutePage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(publicRoutePage)
    await beginSidebarAnimationSampling(publicRoutePage)
    await publicRoutePage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForRunningSidebarAnimation(publicRoutePage)
    await publicRoutePage.evaluate(() => {
      history.pushState({}, '', '/')
      window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
    })
    await publicRoutePage.locator('.landing-page').waitFor({ state: 'visible' })
    const cleanup = await publicRoutePage.evaluate(() => {
      const targets = window.__dashboardSidebarMotionTargets || {}
      const elements = [targets.shell, targets.sidebar, targets.main, ...(targets.nav || [])].filter(Boolean)
      const activeAnimations = elements.flatMap((node) => node.getAnimations())
        .filter((animation) => animation.playState === 'running' || animation.playState === 'pending')
      return {
        appShellRemoved: !document.querySelector('.app-shell'),
        targetsDetached: elements.length > 0 && elements.every((node) => !node.isConnected),
        activeAnimations: activeAnimations.map((animation) => ({ target: animation.effect?.target?.className || '', state: animation.playState })),
      }
    })
    assert.equal(cleanup.appShellRemoved, true, 'public route should use its independent shell')
    assert.equal(cleanup.targetsDetached, true, 'independent public route should unmount the learning shell')
    assert.deepEqual(cleanup.activeAnimations, [], 'unmounted learning sidebar should leave no active WAAPI animations')
    state.evidence.sidebarAnimationChecks.push({ label: 'public-shell-unmount-cancellation', ...cleanup })
  } finally {
    await publicRoutePage.close()
  }
}

async function testSidebarMidframeScreenshots(browser, base) {
  const normalPage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(normalPage)
    await normalPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    const collapse = await captureSidebarMidframe(normalPage, 'normal-collapse', true)
    await waitForSidebarState(normalPage, true)

    await normalPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    const expand = await captureSidebarMidframe(normalPage, 'normal-expand', false)
    await waitForSidebarState(normalPage, false)
    const final = await assertSidebarRest(normalPage, false, 'midframe-screenshot-normal-final')
    state.evidence.sidebarMidframeChecks.push({ collapse, expand, final: final.snapshot })
  } finally {
    await normalPage.close()
  }

  const rapidPage = await newFixturePage(browser, base, { width: 1393, height: 871 }, 'route-smoke')
  try {
    await waitForDashboard(rapidPage)
    await rapidPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForSidebarTimelineProgress(rapidPage, true, 0.2, 0.4)
    await rapidPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    const rapid = await captureSidebarMidframe(rapidPage, 'rapid-reversal', false)
    assert.equal(await rapidPage.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-animating')), true,
      'rapid reversal midpoint screenshot should resume an active transition')
    await rapidPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await rapidPage.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(true))))
    await rapidPage.evaluate(() => document.querySelector('.sidebar-toggle')?.click())
    await waitForSidebarState(rapidPage, false)
    const final = await assertSidebarRest(rapidPage, false, 'midframe-screenshot-rapid-final')
    state.evidence.sidebarMidframeChecks.push({ rapid, rapidReversalsAfterCapture: 2, final: final.snapshot })
  } finally {
    await rapidPage.close()
  }
}

async function testViewportMatrix(browser, base) {
  state.scenario = 'with-resources'
  for (const viewport of viewports) {
    const page = await newFixturePage(browser, base, viewport, 'with-resources')
    try {
      await waitForDashboard(page)
      assert.equal(await page.locator('.app-shell.is-dashboard').count(), 1, viewport.name + ': dashboard shell class missing')
      await checkViewportState(page, viewport, false)

      const toggle = page.locator('.sidebar-toggle')
      assert.equal(await toggle.count(), 1, viewport.name + ': sidebar toggle missing')
      assert.ok(await toggle.getAttribute('aria-label'), viewport.name + ': sidebar toggle needs an accessible name')
      assert.equal(await toggle.getAttribute('aria-expanded'), 'true', viewport.name + ': expanded sidebar state is not exposed')
      const navItems = page.locator('.nav-list .nav-item')
      assert.equal(await navItems.count(), 5, viewport.name + ': all original sidebar destinations should remain')
      for (let index = 0; index < await navItems.count(); index += 1) {
        assert.ok(await navItems.nth(index).getAttribute('aria-label'), viewport.name + ': sidebar icon needs an accessible name')
      }
      await toggle.click()
      await checkViewportState(page, viewport, true)
      assert.equal(await toggle.getAttribute('aria-expanded'), 'false', viewport.name + ': collapsed sidebar state is not exposed')
      assert.ok((await toggle.getAttribute('aria-label')).includes('展开'), viewport.name + ': collapsed toggle should announce expand')

      await page.reload({ waitUntil: 'domcontentloaded' })
      await waitForDashboard(page)
      assert.equal(await page.locator('.app-shell.is-sidebar-collapsed.is-dashboard').count(), 1, viewport.name + ': collapsed sidebar did not persist after reload')
      assert.equal(await page.evaluate(() => localStorage.getItem('app_sidebar_collapsed')), 'true')
      await checkViewportState(page, viewport, true, false)
      state.evidence.sidebarChecks.push({
        viewport: viewport.name,
        expandedAria: 'true',
        collapsedAria: 'false',
        persistedValue: 'true',
      })
    } finally {
      await page.close()
    }
  }
}

async function testRecommendationBranches(browser, base) {
  const cases = [
    { scenario: 'no-profile', title: '先建立学习方向', path: '/learning/new' },
    { scenario: 'profile-no-resources', title: '生成第一批学习资源', path: '/generate' },
    { scenario: 'with-resources', title: '继续阅读本轮学习资源', path: '/resources' },
  ]
  for (const item of cases) {
    const viewport = { width: 1393, height: 871 }
    const page = await newFixturePage(browser, base, viewport, item.scenario)
    try {
      await waitForDashboard(page)
      const title = await page.locator('.next-action-title').innerText()
      assert.ok(title.includes(item.title), item.scenario + ': unexpected next-step title ' + title)
      const layout = await page.evaluate(() => {
        const readRect = (node) => {
          if (!node) return null
          const rect = node.getBoundingClientRect()
          return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height }
        }
        const selectors = ['.hero-copy h2', '.next-action-title', '.hero-copy p', '.hero-actions', '.hero-footnote']
        const text = selectors.map((selector) => {
          const node = document.querySelector(selector)
          const rect = readRect(node)
          const style = node ? getComputedStyle(node) : null
          return {
            selector,
            text: node?.innerText?.trim() || node?.textContent?.trim() || '',
            rect,
            visible: Boolean(node && rect && rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'),
            scrollWidth: node?.scrollWidth ?? 0,
            clientWidth: node?.clientWidth ?? 0,
            scrollHeight: node?.scrollHeight ?? 0,
            clientHeight: node?.clientHeight ?? 0,
          }
        })
        const copy = readRect(document.querySelector('.hero-copy'))
        const visual = readRect(document.querySelector('.hero-visual'))
        const hero = readRect(document.querySelector('.home-hero'))
        const buttons = [...document.querySelectorAll('.hero-actions .workbench-primary, .hero-actions .workbench-history')].map((node) => ({
          selector: node.className,
          text: node.innerText.trim(),
          rect: readRect(node),
          disabled: node.matches(':disabled'),
        }))
        const summary = [...document.querySelectorAll('.summary-item')].map((node) => ({
          label: node.querySelector('.summary-label')?.textContent.trim() || '',
          value: node.querySelector('.summary-value strong')?.textContent.trim() || '',
          rect: readRect(node),
        }))
        const intersects = (left, right) => left && right && left.left < right.right - 1 && right.left < left.right - 1
          && left.top < right.bottom - 1 && right.top < left.bottom - 1
        const sequenceOverlaps = text.slice(1).map((item, index) => text[index].rect && item.rect && text[index].rect.bottom > item.rect.top + 1)
        return {
          viewport: { width: innerWidth, height: innerHeight },
          fit: document.querySelector('.home-page')?.classList.contains('is-fit-layout') || false,
          hero,
          copy,
          visual,
          copyVisualOverlap: intersects(copy, visual),
          copyVisualGap: copy && visual ? (visual.left >= copy.right ? visual.left - copy.right : copy.left - visual.right) : null,
          sequenceOverlaps,
          text,
          buttons,
          summary,
          toolAndLoop: [readRect(document.querySelector('.learning-tools')), readRect(document.querySelector('.learning-route-panel'))],
        }
      })
      assert.equal(layout.fit, true, item.scenario + ': 1393x871 should retain the measured one-screen workbench')
      assert.ok(layout.hero && layout.copy && layout.visual, item.scenario + ': hero copy and visual regions should both render')
      assert.equal(layout.copyVisualOverlap, false, item.scenario + ': hero copy and visual should not overlap')
      assert.ok(layout.copyVisualGap >= -1 && layout.copyVisualGap <= 180, item.scenario + ': hero content should use the middle space without leaving a large gap')
      assert.ok(layout.text.every((node) => node.visible && node.text), item.scenario + ': all hero text should remain visible and readable')
      assert.ok(layout.text.every((node) => node.scrollWidth <= node.clientWidth + 1 && node.scrollHeight <= node.clientHeight + 1),
        item.scenario + ': hero text should not be clipped')
      assert.ok(layout.sequenceOverlaps.every((overlap) => !overlap), item.scenario + ': hero title, recommendation, description, actions and note should not overlap')
      assert.equal(layout.buttons.length, 2, item.scenario + ': both original hero actions should remain')
      assert.ok(layout.buttons.every((button) => button.text && button.rect && button.rect.width > 0 && button.rect.height > 0),
        item.scenario + ': both hero actions should be fully visible')
      assert.equal(layout.summary.length, 4, item.scenario + ': the original four summary metrics should remain')
      assert.ok(layout.summary.every((metric) => metric.label && metric.value && metric.rect?.height > 0), item.scenario + ': summary labels and values should remain readable')
      const filename = 'hero-branch-' + item.scenario + '-1393x871.png'
      const screenshot = await page.screenshot({ path: path.join(reportDir, filename) })
      state.evidence.screenshots.push({ filename, width: screenshot.readUInt32BE(16), height: screenshot.readUInt32BE(20), viewport })
      state.evidence.heroLayoutChecks.push({ scenario: item.scenario, expectedTitle: item.title, layout })
      const route = await assertRouteClick(page, '.workbench-primary', item.path, item.scenario + ' recommendation')
      state.evidence.recommendationBranches.push({
        scenario: item.scenario,
        title,
        expectedPath: item.path,
        actualPath: route?.actualPath || item.path,
      })
    } finally {
      await page.close()
    }
  }
}

async function testRouteEntries(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'route-smoke')
  try {
    await waitForDashboard(page)
    const nav = [
      ['工作台', '/dashboard'],
      ['新建方向', '/learning/new'],
      ['资源生成', '/generate'],
      ['学习资源', '/resources'],
      ['学习反馈', '/feedback'],
    ]
    for (const [label, expectedPath] of nav) {
      const link = page.locator('.nav-list .nav-item[aria-label="' + label + '"]')
      assert.equal(await link.count(), 1, 'navigation aria-label missing: ' + label)
      assert.equal(await link.getAttribute('href'), expectedPath, 'navigation route changed: ' + label)
      await actionReachable(page, '.nav-list .nav-item[aria-label="' + label + '"]', 'navigation ' + label)
    }

    const toolRoutes = ['/resources', '/feedback', '/report', '/learning/history']
    assert.equal(await page.locator('.tool-card').count(), 4, 'the four original quick entries must remain')
    for (let index = 0; index < toolRoutes.length; index += 1) {
      await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
      await waitForDashboard(page)
      await assertRouteClick(page, '.tool-card:nth-of-type(' + (index + 1) + ')', toolRoutes[index], 'quick entry ' + (index + 1))
    }

    const topbarRoutes = ['/learning/history', '/report', '/user/profile']
    assert.equal(await page.locator('.topbar .topbar-action').count(), 3, 'the three original topbar actions must remain')
    for (let index = 0; index < topbarRoutes.length; index += 1) {
      await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
      await waitForDashboard(page)
      await assertRouteClick(page, '.topbar .topbar-action:nth-of-type(' + (index + 1) + ')', topbarRoutes[index], 'topbar action ' + (index + 1))
    }

    const primaryRoute = '/learning/new'
    await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
    await waitForDashboard(page)
    await assertRouteClick(page, '.workspace-new', primaryRoute, 'new direction entry')
    await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' })
    await waitForDashboard(page)
    await assertRouteClick(page, '.hero-actions .workbench-history', '/learning/history', 'hero history entry')
  } finally {
    await page.close()
  }
}

async function testFocusContrastAndMotion(browser, base) {
  const page = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'with-resources')
  try {
    await waitForDashboard(page)
    await page.waitForFunction(() => {
      const button = document.querySelector('.workspace-switch')
      return button && !button.disabled && getComputedStyle(button).opacity === '1'
    })
    await page.keyboard.press('Tab')
    const focus = await page.evaluate(() => {
      const node = document.activeElement
      const style = getComputedStyle(node)
      const visible = node.matches(':focus-visible')
      return {
        tag: node.tagName,
        className: node.className,
        ariaLabel: node.getAttribute('aria-label'),
        focusVisible: visible,
        outlineStyle: style.outlineStyle,
        outlineWidth: Number.parseFloat(style.outlineWidth),
        outlineColor: style.outlineColor,
      }
    })
    assert.equal(focus.focusVisible, true, 'keyboard Tab should produce :focus-visible')
    assert.notEqual(focus.outlineStyle, 'none', 'keyboard focus needs a visible outline')
    assert.ok(focus.outlineWidth >= 2, 'keyboard focus outline must have visible width')
    assert.notEqual(focus.outlineColor, 'rgba(0, 0, 0, 0)', 'keyboard focus outline must not be transparent')
    state.evidence.focusChecks.push(focus)

    const selectors = [
      '.hero-copy h2',
      '.hero-copy p',
      '.workspace-switch',
      '.workbench-primary',
      '.workbench-history',
      '.next-action-title',
      '.summary-label',
      '.summary-value strong',
      '.summary-code',
      '.tool-copy strong',
      '.tool-copy small',
      '.route-list li span',
      '.route-list li small',
    ]
    const heroBackground = await page.locator('.home-hero').evaluate((node) => {
      const style = getComputedStyle(node)
      return { color: style.backgroundColor, image: style.backgroundImage }
    })
    assert.equal(heroBackground.image, 'none', 'hero text must not sit over an unmeasured gradient')
    assert.equal(heroBackground.color.toLowerCase(), 'rgb(16, 31, 53)', 'hero panel should retain the approved solid #101f35 base')
    state.evidence.contrastChecks = await textContrast(page, selectors)
    const summary = await page.locator('.summary-item').evaluateAll((items) => items.map((item) => ({
      label: item.querySelector('.summary-label')?.textContent.trim() || '',
      value: item.querySelector('.summary-value')?.innerText.trim() || '',
      code: item.querySelector('.summary-code')?.textContent.trim() || '',
      codeVisible: (() => {
        const node = item.querySelector('.summary-code')
        const rect = node?.getBoundingClientRect()
        const style = node ? getComputedStyle(node) : null
        return Boolean(node && rect && rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden')
      })(),
      hasIcon: Boolean(item.querySelector('.summary-icon svg')),
      iconAnimated: Boolean(item.querySelector('.summary-icon svg animate, .summary-icon svg animateMotion, .summary-icon svg animateTransform, .summary-icon svg set')),
    })))
    assert.equal(summary.length, 4, 'summary redesign should retain four real metrics')
    assert.ok(summary.every((item) => item.label && item.value && item.code && item.codeVisible && item.hasIcon && !item.iconAnimated),
      'each summary metric should expose an icon, label, value and code ' + JSON.stringify(summary))
    assert.ok(summary.find((item) => item.label.includes('资源'))?.value.includes('1 份'), 'resource metric should keep the complete value “1 份”')
    state.evidence.summaryStructureChecks.push(...summary)

    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const motion = await page.evaluate(() => ({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      running: document.getAnimations({ subtree: true })
        .filter((animation) => animation.playState === 'running' || animation.playState === 'pending')
        .map((animation) => ({
          name: animation.animationName || animation.constructor.name,
          target: animation.effect?.target?.className || animation.effect?.target?.tagName || '',
        })),
    }))
    assert.equal(motion.reduced, true)
    assert.deepEqual(motion.running, [], 'reduced motion should leave no running dashboard decoration')
    state.evidence.reducedMotionChecks.push(motion)
  } finally {
    await page.close()
  }
}

async function testLongTextLoadingAndFailure(browser, base) {
  const longPage = await newFixturePage(browser, base, { width: 375, height: 667 }, 'long-text')
  try {
    await waitForDashboard(longPage)
    await geometry(longPage, 'long user and direction text', false)
    const longText = await longPage.evaluate(() => {
      const direction = document.querySelector('.hero-copy h2')
      const user = document.querySelector('.topbar-meta strong')
      const inspect = (node) => {
        if (!node) return null
        const style = getComputedStyle(node)
        return {
          text: node.textContent.trim(),
          whiteSpace: style.whiteSpace,
          overflow: style.overflow,
          textOverflow: style.textOverflow,
          clientWidth: node.clientWidth,
          scrollWidth: node.scrollWidth,
          clientHeight: node.clientHeight,
          scrollHeight: node.scrollHeight,
        }
      }
      return { direction: inspect(direction), user: inspect(user) }
    })
    assert.ok(longText.direction?.text.includes(directionFor('long-text')), 'long direction should remain readable in the hero')
    assert.ok(longText.user?.text.includes(userFor('long-text').username), 'long username should remain readable in the shell')
    for (const [label, item] of Object.entries(longText)) {
      assert.ok(item, label + ' text target missing')
      assert.notEqual(item.whiteSpace, 'nowrap', label + ' should wrap rather than truncate')
      assert.ok(item.scrollWidth <= item.clientWidth + 1, label + ' text is clipped horizontally')
    }
    state.evidence.longTextChecks.push(longText)
  } finally {
    await longPage.close()
  }

  const loadingPage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'loading')
  try {
    await loadingPage.waitForFunction(() => (
      document.querySelector('.home-hero')?.getAttribute('aria-busy') === 'true'
      && document.querySelector('.learning-summary')?.getAttribute('aria-busy') === 'true'
    ))
    state.evidence.loadingChecks.push({ heroAriaBusyObserved: true, summaryAriaBusyObserved: true })
    await waitForSummary(loadingPage)
    assert.equal(await loadingPage.locator('.home-hero').getAttribute('aria-busy'), 'false')
    assert.equal(await loadingPage.locator('.learning-summary').getAttribute('aria-busy'), 'false')
  } finally {
    await loadingPage.close()
  }

  const failedPage = await newFixturePage(browser, base, { width: 1280, height: 800 }, 'summary-failure')
  try {
    await waitForSummary(failedPage)
    await failedPage.getByText('当前学习摘要加载失败').waitFor({ state: 'visible' })
    assert.equal(await failedPage.locator('.home-hero').getAttribute('aria-busy'), 'false')
    assert.equal(await failedPage.locator('.learning-summary').getAttribute('aria-busy'), 'false')
    state.evidence.loadingChecks.push({ failureMessage: '当前学习摘要加载失败', ariaBusyReset: true })
  } finally {
    await failedPage.close()
  }
}

async function main() {
  const server = makeServer()
  let browser
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const base = 'http://127.0.0.1:' + server.address().port
  state.evidence.base = base
  try {
    browser = await chromium.launch(browserOptions('DASHBOARD_BROWSER_CHANNEL'))
    await testDesktopFixedLayout(browser, base)
    await testViewportMatrix(browser, base)
    await testSharedSidebarRoutesAndKeyboard(browser, base)
    await testSidebarAnimationLifecycle(browser, base)
    await testSidebarMidframeScreenshots(browser, base)
    await testRecommendationBranches(browser, base)
    await testRouteEntries(browser, base)
    await testFocusContrastAndMotion(browser, base)
    await testLongTextLoadingAndFailure(browser, base)
    await testResizeAndNaturalReading(browser, base)
    await testLongDirectionDesktopFallback(browser, base)
    await testOtherBusinessPageScroll(browser, base)
    await testProfilePickerEmptyAndSingle(browser, base)
    await testProfilePickerSelectionPersistenceAndKeyboard(browser, base)
    await testProfilePickerLoadingAndRetry(browser, base)
    await testProfilePickerPaginationAndMobileScroll(browser, base)
    await testProfilePickerRequestRace(browser, base)
    await testProfileAndWorkbenchAlignment(browser, base)

    assert.deepEqual(state.writes, [], 'dashboard entry routes must not issue business writes')
    assert.deepEqual(state.errors, [], 'fixture server should not fail')
    assert.deepEqual(state.evidence.browserErrors, [], 'dashboard browser should have no uncaught exceptions')
    state.evidence.api = { requests: state.requests, writes: state.writes }
    state.evidence.status = 'PASS'
    console.log('dashboard browser fixture passed: ' + state.evidence.viewportChecks.length + ' viewport states, '
      + state.evidence.recommendationBranches.length + ' recommendation branches, '
      + state.evidence.routeChecks.length + ' route entries, '
      + state.evidence.fixedLayoutChecks.length + ' fixed desktop states, '
      + state.evidence.sidebarRouteChecks.length + ' shared-sidebar routes, '
      + state.evidence.sidebarAnimationChecks.length + ' sidebar animation states, '
      + state.evidence.sidebarMidframeChecks.length + ' midpoint screenshot groups, '
      + state.evidence.heroLayoutChecks.length + ' hero recommendation layouts, '
      + state.evidence.profilePickerChecks.length + ' profile picker states, '
      + state.evidence.profileAlignmentChecks.length + ' profile alignment states')
  } catch (error) {
    state.evidence.status = 'FAIL'
    state.evidence.failures.push({
      message: error.message,
      stack: error.stack,
    })
    console.error('dashboard browser fixture failed: ' + error.stack)
    process.exitCode = 1
  } finally {
    state.evidence.api = { requests: state.requests, writes: state.writes }
    state.evidence.fixtureErrors = state.errors
    await browser?.close()
    await new Promise((resolve) => server.close(resolve))
    writeFileSync(summaryPath, JSON.stringify(state.evidence, null, 2) + '\n', 'utf8')
  }
}

await main()
