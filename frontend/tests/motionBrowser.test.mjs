import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const expectedMotionEasing = 'cubic-bezier(0.22, 1, 0.36, 1)'
const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'motion-ui')
const summaryPath = path.join(evidenceDir, 'summary.json')
if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before motion browser verification')
}
mkdirSync(evidenceDir, { recursive: true })

const summary = {
  status: 'RUNNING', evidence_type: 'browser_fixture', checks: [], failures: [], screenshots: [],
  nativeTransitions: [], moduleAnimations: [], layoutAnimations: [], requests: [], writes: [], unexpectedApi: [],
  externalRequests: [], pageErrors: [], unhandledRejections: [],
}
const learnerProfiles = [
  { learner_id: 'learner-A', learner_type: '画像 A', knowledge_base_id: 'track-A', skill_level: '初级', learning_goal: '方向 A', learning_preferences: { metadata: { user_profile_snapshot: { display_name: '画像 A' } } } },
  { learner_id: 'learner-B', learner_type: '画像 B', knowledge_base_id: 'track-B', skill_level: '中级', learning_goal: '方向 B', learning_preferences: { metadata: { user_profile_snapshot: { display_name: '画像 B' } } } },
]
const user = { user_id: 'motion-fixture-user', username: 'motion-fixture', display_name: '动效验收用户' }
let authMeUser = user
const domainCatalog = {
  domains: [{
    domain_id: 'domain-A', name: '人工智能', description: '本地动效 fixture 领域',
    tracks: [
      { track_id: 'track-A', knowledge_base_id: 'track-A', name: '检索增强生成', metadata: { available: true, document_count: 2, skill_node_count: 2 } },
      { track_id: 'track-B', knowledge_base_id: 'track-B', name: '知识图谱', metadata: { available: true, document_count: 1, skill_node_count: 1 } },
    ],
  }],
}
const resources = [
  { id: 'resource-1', resource_id: 'resource-1', learner_id: 'learner-A', run_id: 'run-A', batch_id: 'batch-A', resource_type: '讲义', resource_kind: 'learning_document', title: '材料一', topic: '材料一', difficulty: '初级', content_text: '# 材料一\n\n第一份本地验收材料。', knowledge_points: ['节点 A'], source_refs: [], created_at: '2026-10-01T08:00:00Z' },
  { id: 'resource-2', resource_id: 'resource-2', learner_id: 'learner-A', run_id: 'run-A', batch_id: 'batch-A', resource_type: '实操指南', resource_kind: 'learning_document', title: '材料二', topic: '材料二', difficulty: '中级', content_text: '# 材料二\n\n第二份本地验收材料。', knowledge_points: ['节点 B'], source_refs: [], created_at: '2026-10-01T08:01:00Z' },
]
const reportStreams = new Set()
let reportRevision = 1
let reportResourceCount = 107

function writeJson(response, value, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(value))
}

function fixtureReport(windowDays) {
  return {
    learner_id: 'learner-A', window: { window_days: windowDays }, skill_level: '初级',
    report_revision: `motion-report-${windowDays}-${reportRevision}`.padEnd(64, '0'),
    metric_summary: { resource_count: reportResourceCount, feedback_count: 3, weak_point_count: 1, average_correct_rate: 0.72 },
    learning_activity: { verified_accuracy: 0.72 },
    learning_node_mastery_map: { nodes: [], summary: { total_node_count: 0, measured_node_count: 0 } },
    radar: { dimensions: [], values: [] }, resource_difficulty_curve: { points: [] }, learning_path_graph: { nodes: [], edges: [] },
    next_suggestions: ['继续巩固证据检索'],
  }
}

function fixtureJourney(learnerId) {
  const profile = learnerProfiles.find((item) => item.learner_id === learnerId)
  return {
    learner_id: learnerId, profile,
    current_state: { current_nodes: [{ knowledge_point_id: learnerId === 'learner-B' ? '节点 B' : '节点 A' }], completed_nodes: [], latest_assessment: null, next_action: '继续学习' },
    rounds: [], total_rounds: 0, next_offset: null, unlinked_events: [],
  }
}

function apiResponse(url, method, response) {
  const record = { method, path: url.pathname, query: url.search }
  summary.requests.push(record)
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    summary.writes.push(record)
    writeJson(response, { message: 'Motion fixture rejects business writes' }, 403)
    return
  }

  const p = url.pathname
  if (p === '/api/auth/me') return writeJson(response, { user: authMeUser })
  if (p === '/api/profiles/') return writeJson(response, { items: learnerProfiles, total: learnerProfiles.length, page: 1, page_size: 50 })
  if (p === '/api/knowledge/domains') return writeJson(response, domainCatalog)
  if (p === '/api/skills/nodes') return writeJson(response, { nodes: [] })
  if (p === '/api/onboarding/questions') {
    const questions = Array.from({ length: 12 }, (_, index) => ({
      question_id: `q-${index + 1}`, title: `动效问卷问题 ${index + 1}：请描述你的学习目标与应用场景`,
      type: 'text', required: index === 0, hint: '请结合实际背景、当前经验和希望解决的问题补充说明。'.repeat(2),
    }))
    return writeJson(response, { questions })
  }
  if (p === '/api/generate/jobs') return writeJson(response, { items: [{
    learner_id: 'learner-A', run_id: 'run-A', batch_id: 'batch-A', job_status: 'completed', status: 'completed',
    created_at: '2026-10-01T08:00:00Z', finished_at: '2026-10-01T08:05:00Z',
    request_payload: { learner_id: 'learner-A', resource_types: ['讲义', '实操指南'] },
    resource_ids: resources.map((item) => item.resource_id), resource_progress_summary: { total: 2, completed: 2, published: 2, failed: 0 },
  }], total: 1 })
  if (p === '/api/resources/courseware/jobs') return writeJson(response, { items: [], total: 0 })
  if (p === '/api/resources/learner-A') return writeJson(response, { resources })
  if (p === '/api/resource-library/learner-A') return writeJson(response, resources)
  if (p === '/api/resources/items/resource-1' || p === '/api/resources/items/resource-2') {
    const item = resources.find((resource) => resource.resource_id === p.split('/').at(-1))
    return writeJson(response, { resource: item })
  }
  if (p === '/api/runs/run-A/timeline') return writeJson(response, { events: [], has_more: false, last_sequence: 0, next_event_sequence: null })
  if (p === '/api/runs/run-A/claims') return writeJson(response, { resource_reports: [] })
  if (p === '/api/feedback/results/learner-A' || p === '/api/feedback/attempts/learner-A') return writeJson(response, [])
  if (p.startsWith('/api/feedback/evaluation/')) return writeJson(response, { learner_id: 'learner-A', topic: '本地验收', questions: [], resource_ids: ['resource-1'], evaluation: { questions: [] } })
  const historyMatch = p.match(/^\/api\/learning-history\/(learner-[AB])\/journey$/)
  if (historyMatch) return writeJson(response, fixtureJourney(historyMatch[1]))
  const reportMatch = p.match(/^\/api\/report\/(learner-[AB])$/)
  if (reportMatch) return writeJson(response, fixtureReport(Number(url.searchParams.get('window_days') || 30)))
  if (p.startsWith('/api/report/') && p.endsWith('/events')) {
    const learnerId = p.split('/')[3]
    const windowDays = Number(url.searchParams.get('window_days') || 30)
    response.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache', connection: 'keep-alive' })
    response.write(`event: report_snapshot\ndata: ${JSON.stringify({ learner_id: learnerId, window_days: windowDays, report_revision: fixtureReport(windowDays).report_revision })}\n\n`)
    const stream = { learnerId, windowDays, response }
    reportStreams.add(stream)
    response.on('close', () => reportStreams.delete(stream))
    return
  }
  if (p.startsWith('/api/runs/') && p.endsWith('/events')) {
    response.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache', connection: 'keep-alive' })
    response.write(': motion fixture connected\n\n')
    response.on('close', () => {})
    return
  }
  const userMatch = p.match(/^\/api\/users\/[^/]+$/)
  if (userMatch) return writeJson(response, { user })

  summary.unexpectedApi.push(record)
  writeJson(response, { message: `Unexpected motion fixture API: ${p}` }, 404)
}

const server = createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) return apiResponse(url, request.method || 'GET', response)
  const candidate = path.resolve(distDir, '.' + decodeURIComponent(url.pathname))
  const contained = candidate.startsWith(distDir + path.sep)
  const file = contained && existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(distDir, 'index.html')
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }
  response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' })
  response.end(readFileSync(file))
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const baseUrl = `http://127.0.0.1:${server.address().port}`
let browser
const activeContexts = new Set()

async function createPage(routePath, { reducedMotion, apiMode = 'native', width = 1393, height = 871 } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, ...(reducedMotion ? { reducedMotion } : {}) })
  activeContexts.add(context)
  context.setDefaultTimeout(10000)
  await context.addInitScript(({ apiMode: mode }) => {
    window.__motionAudit = { starts: 0, animations: [], unhandled: [], throwStart: mode === 'throw', pauseModules: false, pausePageEnter: false, pausePageExit: false }
    const nativeStart = document.startViewTransition
    if (mode === 'disabled') {
      Object.defineProperty(document, 'startViewTransition', { configurable: true, writable: true, value: undefined })
    } else if (typeof nativeStart === 'function') {
      Object.defineProperty(document, 'startViewTransition', {
        configurable: true, writable: true,
        value: function (callback, options) {
          window.__motionAudit.starts += 1
          if (window.__motionAudit.throwStart) throw new Error('fixture startViewTransition failure')
          return nativeStart.call(this, callback, options)
        },
      })
    }
    const nativeAnimate = Element.prototype.animate
    Element.prototype.animate = function (keyframes, options) {
      const animation = nativeAnimate.call(this, keyframes, options)
      if (this.hasAttribute('data-motion-module') || this.classList?.contains('content-area') || this.classList?.contains('card-head') || this.id === 'app') {
        window.__motionAudit.animations.push({ element: this, animation, keyframes, options })
        if ((this.hasAttribute('data-motion-module') || this.classList?.contains('card-head')) && window.__motionAudit.pauseModules) animation.pause()
        if (this.id === 'app' && Number(options?.duration) === 260 && window.__motionAudit.pausePageEnter) animation.pause()
        if (this.id === 'app' && Number(options?.duration) === 80 && window.__motionAudit.pausePageExit) animation.pause()
      }
      return animation
    }
    window.addEventListener('unhandledrejection', (event) => {
      const reason = String(event.reason)
      window.__motionAudit.unhandled.push(reason)
      console.error(`MOTION_UNHANDLED:${reason}`)
    })
    localStorage.clear()
    localStorage.setItem('last_learner_id', 'learner-A')
    localStorage.setItem('current_generation_run_id', 'batch-A')
    localStorage.setItem('learning_direction_id', 'track-A')
    localStorage.setItem('learning_direction_name', '检索增强生成')
    localStorage.setItem('current_profile', JSON.stringify({
      learner_id: 'learner-A', learner_type: '画像 A', knowledge_base_id: 'track-A', skill_level: '初级',
      learning_goal: '方向 A', learning_preferences: { metadata: { user_profile_snapshot: { display_name: '画像 A' } } },
    }))
    localStorage.setItem('app_sidebar_collapsed', 'false')
  }, { apiMode })
  await context.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== baseUrl) {
      summary.externalRequests.push(request.url())
      await route.abort()
      return
    }
    if (url.pathname.startsWith('/api/') && request.method() !== 'GET' && request.method() !== 'HEAD' && request.method() !== 'OPTIONS') {
      summary.writes.push({ method: request.method(), path: url.pathname, query: url.search })
      await route.fulfill({ status: 403, json: { message: 'Motion fixture rejects business writes' } })
      return
    }
    await route.continue()
  })
  const page = await context.newPage()
  page.on('pageerror', (error) => summary.pageErrors.push(String(error)))
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().startsWith('MOTION_UNHANDLED:')) {
      summary.unhandledRejections.push(message.text().slice('MOTION_UNHANDLED:'.length))
    }
  })
  await page.goto(baseUrl + routePath, { waitUntil: 'domcontentloaded' })
  return { page, context }
}

function note(name, details = {}) { summary.checks.push({ name, ...details }) }
function failCase(name, error) { summary.failures.push({ name, error: String(error?.stack || error) }) }
async function caseRun(name, callback) {
  try { await callback() }
  catch (error) { failCase(name, error) }
}
async function waitForPage(page, selector) { await page.locator(selector).waitFor({ state: 'visible' }) }
async function waitForPageMotionEnd(page) {
  await page.waitForFunction(() => !document.documentElement.hasAttribute('data-page-motion'), null, { timeout: 4000 })
}
async function waitForModuleMotion(page, selector, startIndex = 0) {
  await page.waitForFunction(({ selector: target, startIndex: index }) => window.__motionAudit.animations
    .slice(index).some((item) => item.element?.matches?.(target) && item.element.hasAttribute('data-motion-module')),
  { selector, startIndex }, { timeout: 5000 })
  const sample = await page.evaluate(({ selector: target, startIndex: index }) => {
    const item = [...window.__motionAudit.animations].slice(index).reverse()
      .find((entry) => entry.element?.matches?.(target) && entry.element.hasAttribute('data-motion-module'))
    const animation = item?.animation
    if (!animation) return null
    const timing = animation.effect.getTiming()
    animation.pause()
    animation.currentTime = Number(timing.duration) * 0.25
    const style = getComputedStyle(item.element)
    const result = {
      selector: target, durationMs: Number(timing.duration), easing: timing.easing,
      keyframes: animation.effect.getKeyframes(), opacity: Number(style.opacity), transform: style.transform,
      elementConnected: item.element.isConnected,
    }
    window.__motionAudit.lastSample = animation
    return result
  }, { selector, startIndex })
  assert.ok(sample, `${selector}: the animated module should be present in the audit`)
  assert.equal(sample.durationMs, 200, `${selector}: module motion must use the actual 200ms WAAPI duration`)
  assert.equal(sample.easing, expectedMotionEasing, `${selector}: module motion must use the shared easing`)
  return sample
}
async function resumeSampledAnimation(page) {
  await page.evaluate(() => {
    window.__motionAudit.lastSample?.play()
    window.__motionAudit.lastSamples?.forEach((animation) => animation.play())
    window.__motionAudit.lastSample = null; window.__motionAudit.lastSamples = null
  })
}
async function releaseMotionAuditPauses(page, { modules = false } = {}) {
  await page.evaluate((releaseModules) => {
    const audit = window.__motionAudit
    if (!audit) return
    audit.pausePageEnter = false
    audit.pausePageExit = false
    if (releaseModules) audit.pauseModules = false
    for (const { element, animation } of audit.animations) {
      const isModule = element?.hasAttribute('data-motion-module') || element?.classList?.contains('card-head')
      if (animation?.playState === 'paused' && (element?.id === 'app' || (releaseModules && isModule))) animation.play()
    }
    if (audit.lastSample?.effect?.target?.id === 'app' || releaseModules) audit.lastSample = null
    if (releaseModules) audit.lastSamples = null
  }, modules)
  await page.waitForFunction(() => !document.documentElement.hasAttribute('data-page-motion'), null, { timeout: 4000 })
  if (modules) {
    await page.waitForFunction(() => document.querySelectorAll('[data-motion-running]').length === 0, null, { timeout: 4000 })
  }
}
async function writeScreenshot(page, name) {
  const file = path.join(evidenceDir, `${name}.png`)
  await page.screenshot({ path: file })
  summary.screenshots.push(file)
}
async function checkNoResidue(page, label) {
  await waitForPageMotionEnd(page)
  const residue = await page.evaluate(() => ({
    pageMotion: document.documentElement.hasAttribute('data-page-motion'),
    namedRegions: [...document.querySelectorAll('[style*="view-transition-name"]')].map((node) => ({ className: node.className, value: node.style.getPropertyValue('view-transition-name') })),
    runningMotion: [...document.querySelectorAll('[data-motion-running]')].map((node) => node.getAttribute('data-motion-running')),
    pageRoots: document.querySelectorAll('.content-area > *').length,
  }))
  assert.equal(residue.pageMotion, false, `${label}: page motion marker must be cleared`)
  assert.deepEqual(residue.namedRegions, [], `${label}: temporary view-transition names must be restored`)
  assert.deepEqual(residue.runningMotion, [], `${label}: WAAPI markers must be cleared`)
  if (residue.pageRoots) assert.equal(residue.pageRoots, 1, `${label}: the page outlet must contain one route root`)
  return residue
}
function readFixtureRequestCount(pathname) { return summary.requests.filter((item) => item.path === pathname).length }

async function focusLayoutTransition(page, entering) {
  const before = await page.evaluate(() => ({ starts: window.__motionAudit.starts, animationCount: window.__motionAudit.animations.length }))
  let pendingAction
  try {
    await page.evaluate(() => { window.__motionAudit.pausePageEnter = true })

    if (!entering) {
      // Hold the real outgoing #app fade while the focus exit control is still mounted.
      await page.evaluate(() => { window.__motionAudit.pausePageExit = true })
      pendingAction = page.locator('.focus-exit').click()
      await page.waitForFunction((startIndex) => window.__motionAudit.animations.slice(startIndex)
        .some((item) => item.element?.id === 'app' && Number(item.options?.duration) === 80), before.animationCount)
      const exitSample = await page.evaluate((startIndex) => {
        const item = [...window.__motionAudit.animations].slice(startIndex).reverse()
          .find((entry) => entry.element?.id === 'app' && Number(entry.options?.duration) === 80)
        const animation = item.animation
        animation.pause(); animation.currentTime = 40
        const app = document.querySelector('#app'); const style = getComputedStyle(app)
        const button = document.querySelector('.focus-exit'); const rect = button.getBoundingClientRect()
        const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        window.__motionAudit.lastSample = animation
        window.__motionAudit.pausePageExit = false
        const timing = animation.effect.getTiming()
        return { selector: '#app', phase: 'exit', durationMs: Number(timing.duration), easing: timing.easing, keyframes: animation.effect.getKeyframes(),
          opacity: Number(style.opacity), transform: style.transform, pageMotion: document.documentElement.dataset.pageMotion,
          buttonConnected: button.isConnected, isHitTarget: hit === button || button.contains(hit) }
      }, before.animationCount)
      assert.equal(exitSample.durationMs, 80, 'focus layout exit must use the 80ms live opacity fade')
      assert.equal(exitSample.easing, expectedMotionEasing, 'focus layout exit must use the shared easing')
      assert.ok(exitSample.opacity > 0.65 && exitSample.opacity < 1, 'focus exit must be sampled during the live #app fade')
      assert.equal(exitSample.transform, 'none', 'focus layout fade must not create a transform containing block')
      assert.equal(exitSample.pageMotion, 'fallback')
      assert.equal(exitSample.buttonConnected, true, 'focus exit control must remain mounted during the outgoing fade')
      assert.equal(exitSample.isHitTarget, true, 'focus exit control must remain the actual hit target during the outgoing fade')
      assert.equal(await page.evaluate(() => window.__motionAudit.starts), before.starts, 'whole-layout focus exit must not start a native view transition')
      summary.layoutAnimations.push(exitSample)
      await writeScreenshot(page, 'focus-exit-live-opacity-midpoint')
      await page.evaluate(() => { window.__motionAudit.lastSample?.play(); window.__motionAudit.lastSample = null })
      await pendingAction
    } else {
      pendingAction = page.locator('.focus-button').click()
      await pendingAction
    }

    await page.waitForFunction((expected) => new URL(location.href).searchParams.has('focus') === expected, entering)
    await page.waitForFunction(({ startIndex, duration }) => window.__motionAudit.animations.slice(startIndex)
      .some((item) => item.element?.id === 'app' && Number(item.options?.duration) === duration),
    { startIndex: before.animationCount, duration: 260 })
    const enterSample = await page.evaluate(({ startIndex, starts, enteringFocus }) => {
      const item = [...window.__motionAudit.animations].slice(startIndex).reverse()
        .find((entry) => entry.element?.id === 'app' && Number(entry.options?.duration) === 260)
      const animation = item.animation
      animation.pause(); animation.currentTime = 130
      const app = item.element; const style = getComputedStyle(app)
      const timing = animation.effect.getTiming()
      const button = enteringFocus ? document.querySelector('.focus-exit') : null
      let isHitTarget = null
      if (button) {
        const rect = button.getBoundingClientRect()
        const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        isHitTarget = hit === button || button.contains(hit)
      }
      window.__motionAudit.lastSample = animation
      return { selector: '#app', phase: 'enter', durationMs: Number(timing.duration), easing: timing.easing, keyframes: animation.effect.getKeyframes(),
        opacity: Number(style.opacity), transform: style.transform, pageMotion: document.documentElement.dataset.pageMotion,
        starts: window.__motionAudit.starts, startsBefore: starts, buttonConnected: button?.isConnected ?? null, isHitTarget }
    }, { startIndex: before.animationCount, starts: before.starts, enteringFocus: entering })
    assert.equal(enterSample.durationMs, 260, 'focus layout enter must use the 260ms live opacity fade')
    assert.equal(enterSample.easing, expectedMotionEasing, 'focus layout enter must use the shared easing')
    assert.ok(enterSample.opacity > 0.55 && enterSample.opacity < 1, 'focus layout must be sampled at a real intermediate #app opacity')
    assert.equal(enterSample.transform, 'none', 'focus layout fade must not create a transform containing block')
    assert.equal(enterSample.pageMotion, 'fallback')
    assert.equal(enterSample.starts, before.starts, 'whole-layout focus navigation must not start a native view transition')
    if (entering) {
      assert.equal(enterSample.buttonConnected, true, 'focus exit control must mount during the incoming fade')
      assert.equal(enterSample.isHitTarget, true, 'focus exit control must be the actual hit target during the incoming fade')
    }
    summary.layoutAnimations.push(enterSample)
    await writeScreenshot(page, entering ? 'focus-entry-live-opacity-midpoint' : 'focus-reader-live-opacity-midpoint')
    await page.evaluate(() => { window.__motionAudit.lastSample?.play(); window.__motionAudit.lastSample = null })
    await page.evaluate(() => { window.__motionAudit.pausePageEnter = false })
    await waitForPageMotionEnd(page)
    return enterSample
  } finally {
    await page.evaluate(() => {
      const audit = window.__motionAudit
      audit.pausePageEnter = false; audit.pausePageExit = false
      for (const { element, animation } of audit.animations) {
        if (element?.id === 'app' && animation?.playState === 'paused') animation.play()
      }
      if (audit.lastSample?.effect?.target?.id === 'app') audit.lastSample = null
    })
    if (pendingAction) await pendingAction.catch(() => {})
    await page.waitForFunction(() => !document.documentElement.hasAttribute('data-page-motion'), null, { timeout: 4000 }).catch(() => {})
  }
}

async function measureNativeTransition(page, selector, name, { screenshot = false } = {}) {
  await page.evaluate(() => {
    window.__shellBefore = ['.sidebar', '.topbar', '.main-area'].map((selector) => {
      const rect = document.querySelector(selector)?.getBoundingClientRect()
      return rect && [rect.x, rect.y, rect.width, rect.height]
    })
  })
  const targetPath = selector.startsWith('/') ? selector : ({
    '学习历史': '/learning/history', '学习报告': '/report', '用户资料': '/user/profile',
  })[selector]
  assert.ok(targetPath, `unknown native navigation target: ${selector}`)
  const targetUrl = new URL(targetPath, baseUrl)
  const navigation = page.waitForFunction((pathname) => location.pathname === pathname, targetUrl.pathname)
  // Start sampling before the click: production transitions are only 120/260ms.
  const samplePromise = page.waitForFunction(() => {
    const oldStyle = getComputedStyle(document.documentElement, '::view-transition-old(app-page)')
    const newStyle = getComputedStyle(document.documentElement, '::view-transition-new(app-page)')
    const oldOpacity = Number(oldStyle.opacity)
    const newOpacity = Number(newStyle.opacity)
    if (!oldStyle.animationName.includes('page-depart') || !newStyle.animationName.includes('page-arrive')) return false
    if (!(oldOpacity > 0.1 && oldOpacity < 0.95 && newOpacity > 0.1 && newOpacity < 0.95)) return false
    const shellNow = ['.sidebar', '.topbar', '.main-area'].map((item) => {
      const rect = document.querySelector(item)?.getBoundingClientRect()
      return rect && [rect.x, rect.y, rect.width, rect.height]
    })
    return { oldName: oldStyle.animationName, newName: newStyle.animationName,
      oldDuration: oldStyle.animationDuration, newDuration: newStyle.animationDuration,
      oldOpacity, newOpacity, oldTransform: oldStyle.transform, newTransform: newStyle.transform,
      shellBefore: window.__shellBefore, shellNow }
  }, null, { timeout: 5000 })
  await page.locator(selector.startsWith('/learning') || selector.startsWith('/generate') || selector.startsWith('/resources') || selector.startsWith('/feedback') || selector.startsWith('/dashboard')
    ? `a.nav-item[href="${selector}"]`
    : `.topbar-actions .el-button:has-text("${selector}")`).click()
  const [sampleHandle] = await Promise.all([samplePromise, navigation])
  const sample = await sampleHandle.jsonValue()
  assert.ok(sample.oldOpacity > 0 && sample.oldOpacity < 1, `${selector}: outgoing pseudo-element must be sampled mid-animation`)
  assert.ok(sample.newOpacity > 0 && sample.newOpacity < 1, `${selector}: incoming pseudo-element must be sampled mid-animation`)
  assert.equal(sample.oldName, 'page-depart')
  assert.equal(sample.newName, 'page-arrive')
  for (let index = 0; index < sample.shellBefore.length; index += 1) {
    for (let axis = 0; axis < 4; axis += 1) assert.ok(Math.abs(sample.shellBefore[index][axis] - sample.shellNow[index][axis]) <= 1, `${selector}: fixed shell geometry changed`)
  }
  summary.nativeTransitions.push({ to: targetUrl.pathname, ...sample })
  if (screenshot) await writeScreenshot(page, name)
  await page.waitForSelector(selector.startsWith('/learning') ? '.onboarding-page'
    : selector.startsWith('/generate') ? '.generate-page'
      : selector.startsWith('/resources') ? '.resources-layout'
        : selector.startsWith('/feedback') ? '.feedback-page'
          : selector === '学习历史' ? '.history-page'
            : selector === '学习报告' ? '.report-page'
              : selector === '用户资料' ? '.user-profile-page' : '.home-page')
  await checkNoResidue(page, selector)
  note('native-spa-navigation', { to: targetUrl.pathname })
}

async function testNativeNavigation() {
  const { page, context } = await createPage('/dashboard')
  try {
    await waitForPage(page, '.home-page')
    assert.equal(await page.evaluate(() => typeof document.startViewTransition), 'function', 'the configured browser must support native View Transitions')
    const destinations = [
      ['/learning/new', 'native-onboarding-midpoint'], ['/generate', 'native-generation-midpoint'],
      ['/resources', 'native-resources-midpoint'], ['/feedback', 'native-feedback-midpoint'],
      ['学习历史', 'native-history-midpoint'], ['学习报告', 'native-report-midpoint'], ['用户资料', 'native-profile-midpoint'],
    ]
    for (let index = 0; index < destinations.length; index += 1) {
      const [destination, screenshotName] = destinations[index]
      await measureNativeTransition(page, destination, screenshotName, { screenshot: index === 0 })
    }
    const starts = await page.evaluate(() => window.__motionAudit.starts)
    assert.ok(starts >= 7, 'each genuine sidebar/topbar route navigation should call the native API')
    await context.close()
  } finally { activeContexts.delete(context) }
}

async function sampleAuthModeMotion(page, startIndex, label) {
  const sample = await waitForModuleMotion(page, '.access-form-panel', startIndex)
  assert.equal(sample.durationMs, 200, `${label}: account form should use the shared module timing`)
  assert.equal(sample.easing, expectedMotionEasing, `${label}: account form should use the shared easing`)
  assert.ok(sample.opacity > 0.55 && sample.opacity < 0.95, `${label}: account form should be sampled between opacity endpoints`)
  assert.equal(sample.transform, 'none', `${label}: account form fade must not move the dialog or scroll region`)
  assert.deepEqual(sample.keyframes.map((frame) => Number(frame.opacity)), [0.55, 1], `${label}: account form should use the shared opacity-only keyframes`)
  const interaction = await page.evaluate(() => {
    const submit = document.querySelector('.access-dialog .access-submit')
    const rect = submit?.getBoundingClientRect()
    const x = rect ? rect.left + rect.width / 2 : -1
    const y = rect ? rect.top + rect.height / 2 : -1
    const hit = x >= 0 && y >= 0 ? document.elementFromPoint(x, y) : null
    const animation = [...window.__motionAudit.animations].reverse()
      .find((entry) => entry.element?.matches?.('.access-form-panel'))?.animation
    return {
      pageMotion: document.documentElement.getAttribute('data-page-motion'),
      nativeStarts: window.__motionAudit.starts,
      marker: document.querySelector('.access-form-panel')?.getAttribute('data-motion-running') || null,
      submitRect: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null,
      inViewport: Boolean(rect && x >= 0 && x < innerWidth && y >= 0 && y < innerHeight),
      hitTarget: Boolean(submit && hit && (hit === submit || submit.contains(hit))),
      animationTargetConnected: Boolean(animation?.effect?.target?.isConnected),
    }
  })
  assert.equal(interaction.pageMotion, null, `${label}: account route swap must not start whole-page motion`)
  assert.equal(interaction.nativeStarts, 0, `${label}: account route swap must not start a native view transition`)
  assert.equal(interaction.marker, 'module', `${label}: account form should be the locally animated module`)
  assert.equal(interaction.inViewport, true, `${label}: submit center should remain inside the viewport during the fade`)
  assert.equal(interaction.hitTarget, true, `${label}: submit must remain hit-testable during the fade`)
  assert.equal(interaction.animationTargetConnected, true, `${label}: local account form must remain mounted during the fade`)
  summary.moduleAnimations.push({ ...sample, interaction })
  await writeScreenshot(page, `auth-${label}-midpoint`)
  await resumeSampledAnimation(page)
  await page.waitForFunction(() => !document.querySelector('.access-form-panel')?.hasAttribute('data-motion-running'))
  return { ...sample, interaction }
}

async function testAuthModeMotion() {
  authMeUser = null
  let context
  let page
  try {
    const created = await createPage('/login?auth=1')
    page = created.page
    context = created.context
    await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
    await page.waitForFunction(() => !document.documentElement.hasAttribute('data-page-motion'))
    const baseline = await page.evaluate(() => ({ starts: window.__motionAudit.starts, writes: window.__motionAudit.animations.length }))

    let startIndex = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    await page.getByRole('link', { name: '创建账号', exact: true }).click()
    await page.getByRole('dialog', { name: '注册账号', exact: true }).waitFor()
    const register = await sampleAuthModeMotion(page, startIndex, 'login-to-register')

    startIndex = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    await page.getByRole('link', { name: '返回登录', exact: true }).click()
    await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
    const login = await sampleAuthModeMotion(page, startIndex, 'register-to-login')

    const final = await page.evaluate(() => ({
      starts: window.__motionAudit.starts,
      pageMotion: document.documentElement.hasAttribute('data-page-motion'),
      running: document.querySelectorAll('[data-motion-running]').length,
    }))
    assert.equal(final.starts, baseline.starts, 'account form mode swaps must not add native page transitions')
    assert.equal(final.pageMotion, false, 'account form mode swaps must not leave page-transition state')
    assert.equal(final.running, 0, 'account form mode swaps must clear their local animation markers')
    assert.equal(summary.writes.length, 0, 'the auth motion fixture must not submit login or registration requests')
    note('auth-form-local-fade-hit-test', {
      transitions: ['login-to-register', 'register-to-login'],
      durationMs: register.durationMs,
      nativeStarts: final.starts,
      submitHitDuringFade: [register.interaction.hitTarget, login.interaction.hitTarget],
      writes: summary.writes.length,
    })
  } finally {
    authMeUser = user
    if (context) {
      try {
        if (page) await releaseMotionAuditPauses(page, { modules: true })
      } finally {
        await context.close()
        activeContexts.delete(context)
      }
    }
  }
}

async function testFallback(apiMode, label) {
  const { page, context } = await createPage('/dashboard', { apiMode })
  try {
    await waitForPage(page, '.home-page')
    assert.equal(await page.evaluate(() => typeof document.startViewTransition), apiMode === 'disabled' ? 'undefined' : 'function', `${label}: the fixture must apply the requested native API mode`)
    await page.addStyleTag({ content: ':root{--motion-fallback-exit:700ms;--motion-page-enter:500ms}' })
    const shellBefore = await page.evaluate(() => ['.sidebar', '.topbar', '.main-area'].map((selector) => {
      const rect = document.querySelector(selector).getBoundingClientRect()
      return [rect.x, rect.y, rect.width, rect.height]
    }))
    const navigation = page.waitForFunction(() => location.pathname === '/learning/history')
    await page.locator('.topbar-actions .el-button:has-text("学习历史")').click()
    await page.waitForFunction(() => document.querySelector('.content-area')?.getAttribute('data-motion-running') === 'page-exit')
    const sample = await page.evaluate(() => {
      const element = document.querySelector('.content-area')
      const animation = element.getAnimations().find((item) => item.effect?.target === element)
      if (!animation) return null
      const timing = animation.effect.getTiming()
      animation.pause()
      animation.currentTime = Number(timing.duration) / 2
      const computed = getComputedStyle(element)
      window.__motionAudit.lastSample = animation
      return { duration: timing.duration, easing: timing.easing, keyframes: animation.effect.getKeyframes(), opacity: Number(computed.opacity), transform: computed.transform }
    })
    assert.ok(sample, `${label}: fallback WAAPI animation should be observable`)
    assert.ok(sample.opacity > 0.65 && sample.opacity < 1, `${label}: fallback should expose an intermediate opacity`)
    assert.equal(sample.transform, 'none', `${label}: fallback must not transform the live scroll/fixed containing block`)
    for (let index = 0; index < shellBefore.length; index += 1) {
      const shellNow = await page.evaluate((selector) => {
        const rect = document.querySelector(selector).getBoundingClientRect()
        return [rect.x, rect.y, rect.width, rect.height]
      }, ['.sidebar', '.topbar', '.main-area'][index])
      for (let axis = 0; axis < 4; axis += 1) assert.ok(Math.abs(shellBefore[index][axis] - shellNow[axis]) <= 1, `${label}: shell moved during opacity fallback`)
    }
    await writeScreenshot(page, `${label}-fallback-midpoint`)
    summary.moduleAnimations.push({ name: `${label}-page-exit`, ...sample })
    await resumeSampledAnimation(page)
    try { await navigation }
    catch (error) {
      const diagnostic = await page.evaluate(() => ({ path: location.pathname,
        nativeApi: typeof document.startViewTransition, starts: window.__motionAudit.starts,
        pageMotion: document.documentElement.getAttribute('data-page-motion'),
        running: [...document.querySelectorAll('[data-motion-running]')].map((element) => ({ className: element.className, label: element.getAttribute('data-motion-running') })),
        animations: window.__motionAudit.animations.map(({ animation }) => ({ playState: animation.playState, currentTime: animation.currentTime, timing: animation.effect?.getTiming() })) }))
      throw new Error(`${error.message}; fallback navigation diagnostic=${JSON.stringify(diagnostic)}`)
    }
    await waitForPage(page, '.history-page')
    await checkNoResidue(page, label)
    note('opacity-only-fallback', { mode: apiMode, opacity: sample.opacity, transform: sample.transform })
    await context.close()
  } finally { activeContexts.delete(context) }
}

async function testRapidNavigationAndHistory() {
  const { page, context } = await createPage('/dashboard')
  try {
    await waitForPage(page, '.home-page')
    await page.evaluate(() => {
      document.querySelector('a.nav-item[href="/learning/new"]').click()
      document.querySelector('a.nav-item[href="/generate"]').click()
      document.querySelector('.topbar-actions .el-button:nth-child(2)').click()
    })
    await page.waitForURL('**/report')
    await waitForPage(page, '.report-page')
    assert.equal(new URL(page.url()).pathname, '/report', 'the last rapid SPA navigation should own the final route')
    await checkNoResidue(page, 'rapid-navigation')
    const beforeBack = new URL(page.url()).pathname
    await page.goBack({ waitUntil: 'domcontentloaded' })
    await page.waitForFunction((previous) => location.pathname !== previous, beforeBack)
    await checkNoResidue(page, 'browser-back')
    const backPath = new URL(page.url()).pathname
    await page.goForward({ waitUntil: 'domcontentloaded' })
    await page.waitForFunction((previous) => location.pathname !== previous, backPath)
    await checkNoResidue(page, 'browser-forward')
    note('rapid-navigation-back-forward', { finalPath: new URL(page.url()).pathname, backPath })
    await context.close()
  } finally { activeContexts.delete(context) }
}

async function testResourceReuse() {
  const { page, context } = await createPage('/resources?learnerId=learner-A')
  try {
    await page.locator('.resource-item').nth(1).waitFor()
    await page.locator('.reading-stage .resource-content').filter({ hasText: '第一份本地验收材料' }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.reading-stage')?.hasAttribute('data-motion-running'))
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    const startingCounts = { auth: readFixtureRequestCount('/api/auth/me'), library: readFixtureRequestCount('/api/resource-library/learner-A') }
    await page.evaluate(() => { window.__readingStageBefore = document.querySelector('.reading-stage') })
    const animationStart = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.locator('.resource-item').nth(1).click()
    await page.locator('.reading-stage .resource-content').filter({ hasText: '第二份本地验收材料' }).waitFor()
    await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-2')
    const resourceMotion = await waitForModuleMotion(page, '.reading-stage', animationStart)
    assert.equal(resourceMotion.transform, 'none', 'material selection should fade without translating the reader')
    summary.moduleAnimations.push(resourceMotion)
    assert.equal(await page.evaluate(() => window.__readingStageBefore === document.querySelector('.reading-stage')), true, 'query-only material selection must keep the reading stage mounted')
    assert.equal(readFixtureRequestCount('/api/auth/me'), startingCounts.auth, 'material selection must not reload auth')
    assert.equal(readFixtureRequestCount('/api/resource-library/learner-A'), startingCounts.library, 'material selection must not reload the library')
    await resumeSampledAnimation(page)
    await page.waitForFunction(() => !document.querySelector('.reading-stage')?.hasAttribute('data-motion-running'))

    await page.evaluate(() => { window.__readingStageBeforeFocus = document.querySelector('.reading-stage') })
    const beforeFocusCounts = { auth: readFixtureRequestCount('/api/auth/me'), library: readFixtureRequestCount('/api/resource-library/learner-A') }
    await focusLayoutTransition(page, true)
    await page.locator('.focus-exit').waitFor()
    assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-2', 'focus mode must keep the selected resource in the query')
    assert.equal(await page.evaluate(() => window.__readingStageBeforeFocus !== document.querySelector('.reading-stage')), true, 'focus entry follows the existing App branch and remounts the reader')
    assert.equal(readFixtureRequestCount('/api/auth/me'), beforeFocusCounts.auth, 'focus entry must not reload auth')
    assert.equal(readFixtureRequestCount('/api/resource-library/learner-A'), beforeFocusCounts.library + 1, 'focus entry may load the library once for the newly mounted App branch')
    assert.equal(await page.locator('.sidebar, .topbar').count(), 0, 'focus mode must hide the workbench shell')
    assert.equal(await page.locator('#app > *').count(), 1, 'focus mode must keep one route root')
    const exitControl = await page.locator('.focus-exit').evaluate((button) => {
      const rect = button.getBoundingClientRect(); const style = getComputedStyle(button)
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
      return { position: style.position, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
        viewportWidth: innerWidth, viewportHeight: innerHeight, isHitTarget: hit === button || button.contains(hit) }
    })
    assert.equal(exitControl.position, 'fixed', 'focus exit must stay viewport-fixed')
    assert.ok(exitControl.left >= 0 && exitControl.top >= 0 && exitControl.right <= exitControl.viewportWidth && exitControl.bottom <= exitControl.viewportHeight, 'focus exit must remain inside the viewport')
    assert.equal(exitControl.isHitTarget, true, 'focus exit must not be covered by the page')
    const beforeExitCounts = { auth: readFixtureRequestCount('/api/auth/me'), library: readFixtureRequestCount('/api/resource-library/learner-A') }
    await page.evaluate(() => { window.__readingStageBeforeExit = document.querySelector('.reading-stage') })
    await focusLayoutTransition(page, false)
    assert.equal(await page.evaluate(() => window.__readingStageBeforeExit !== document.querySelector('.reading-stage')), true, 'focus exit follows the existing App branch and remounts the reader')
    assert.match(await page.locator('.reading-stage .resource-content').textContent(), /第二份本地验收材料/)
    assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-2', 'focus exit must retain the selected resource')
    assert.equal(readFixtureRequestCount('/api/auth/me'), beforeExitCounts.auth, 'focus exit must not reload auth')
    assert.equal(readFixtureRequestCount('/api/resource-library/learner-A'), beforeExitCounts.library + 1, 'focus exit may load the library once for the restored App branch')
    assert.equal(await page.locator('#app > *').count(), 1, 'reader mode must restore a single app root')
    note('resource-query-and-focus-reuse', { selectedResource: new URL(page.url()).searchParams.get('resourceId'), exitControl })
  } finally {
    try {
      await releaseMotionAuditPauses(page, { modules: true })
    } finally {
      await context.close()
      activeContexts.delete(context)
    }
  }
}

async function sampleOnboardingStep(page, expectedDirection, start, evidenceName) {
  const sample = await waitForModuleMotion(page, '.step-panel', start)
  assert.equal(sample.elementConnected, true)
  const direction = await page.evaluate(({ startIndex }) => {
    const entry = [...window.__motionAudit.animations].slice(startIndex).reverse()
      .find((item) => item.element?.matches?.('.card-head') && item.element.getAttribute('data-motion-running') === 'module-direction')
    const animation = entry?.animation
    if (!animation) return null
    const timing = animation.effect.getTiming()
    animation.pause()
    animation.currentTime = Number(timing.duration) * 0.25
    const style = getComputedStyle(entry.element)
    const transform = style.transform
    const translation = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m41
    window.__motionAudit.lastSamples = [window.__motionAudit.lastSample, animation]
    window.__motionAudit.lastSample = null
    return { selector: '.card-head', durationMs: Number(timing.duration),
      easing: timing.easing, keyframes: animation.effect.getKeyframes(), transform, translation,
      running: entry.element.getAttribute('data-motion-running'), elementConnected: entry.element.isConnected }
  }, { startIndex: start })
  assert.ok(direction, 'the padded card heading should receive the directional motion')
  assert.equal(sample.durationMs, 200, 'step wrapper fade should use the shared module timing')
  assert.equal(sample.easing, expectedMotionEasing, 'step wrapper fade should use the shared easing')
  assert.equal(direction.durationMs, 200, 'step heading slide should use the shared module timing')
  assert.equal(direction.easing, expectedMotionEasing, 'step heading slide should use the shared easing')
  assert.equal(sample.transform, 'none', 'the step wrapper must remain untransformed so layout and scrolling stay stable')
  assert.ok(sample.opacity > 0.5 && sample.opacity < 0.95, 'step wrapper fade should be sampled between its opacity endpoints')
  assert.equal(direction.running, 'module-direction', 'the directional marker should identify the heading animation')
  assert.equal(direction.elementConnected, true)
  assert.ok(Math.abs(direction.translation) <= 8.1, 'heading motion must stay within an 8px horizontal offset')
  if (expectedDirection) assert.equal(Math.sign(direction.translation), expectedDirection, 'heading motion direction must match forward/back navigation')
  summary.moduleAnimations.push({ ...sample, slideTarget: direction })
  await writeScreenshot(page, `onboarding-step-${evidenceName}-midpoint`)
  await resumeSampledAnimation(page)
  await page.waitForFunction(() => !document.querySelector('.step-panel')?.hasAttribute('data-motion-running')
    && !document.querySelector('.step-panel .card-head')?.hasAttribute('data-motion-running'))
  return { ...sample, slideTarget: direction }
}

async function testOnboardingModules() {
  const { page, context } = await createPage('/learning/new', { width: 1280, height: 720 })
  try {
    await page.locator('.domain-stage-card .choice-card').first().waitFor()
    await page.evaluate(() => { window.__stepPanel = document.querySelector('.step-panel') })
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    await page.locator('.domain-stage-card .choice-card').first().click()
    const beforeTrack = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.getByRole('button', { name: '下一步' }).click()
    await page.locator('.track-stage-card').waitFor()
    assert.equal(await page.evaluate(() => window.__stepPanel === document.querySelector('.step-panel')), true, 'onboarding step changes must keep the module wrapper mounted')
    await sampleOnboardingStep(page, 1, beforeTrack, 'domain-to-track')
    const track = page.locator('.track-stage-card .choice-card').filter({ hasText: '检索增强生成' }).first()
    await track.click()
    const beforeQuestionnaire = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.getByRole('button', { name: '下一步' }).click()
    await page.locator('.questionnaire-stage-card').waitFor()
    assert.equal(await page.locator('.card-title').evaluate((element) => document.activeElement === element), true, 'step change must preserve the existing title focus contract')
    await sampleOnboardingStep(page, 1, beforeQuestionnaire, 'track-to-questionnaire')
    const answer = page.locator('.question-block[data-question-id="q-1"] input').first()
    await answer.fill('答案应跨步骤往返保留')
    const beforeInput = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.step-panel, .card-head')).length)
    const beforeTrackBack = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.locator('.progress-card').nth(1).click()
    await page.locator('.track-stage-card').waitFor()
    await sampleOnboardingStep(page, -1, beforeTrackBack, 'questionnaire-to-track')
    const beforeQuestionnaireForward = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.locator('.progress-card').nth(2).click()
    await page.locator('.questionnaire-stage-card').waitFor()
    await sampleOnboardingStep(page, 1, beforeQuestionnaireForward, 'track-to-questionnaire-return')
    assert.equal(await page.locator('.question-block[data-question-id="q-1"] input').first().inputValue(), '答案应跨步骤往返保留', 'back/forward must preserve questionnaire answers')
    await answer.fill('输入期间不应重播步骤动画')
    const afterInput = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.step-panel, .card-head')).length)
    assert.equal(afterInput, beforeInput + 4, 'two step changes should animate wrapper and heading once each; typing must not retrigger either')
    await page.waitForFunction(() => document.querySelector('.onboarding-page')?.classList.contains('is-contained-layout')
      && document.querySelector('.questionnaire-stage-card > .el-card__body')?.getAttribute('aria-label') === '问卷内容')
    const shellBeforeScroll = await page.evaluate(() => ['.sidebar', '.topbar'].map((selector) => {
      const rect = document.querySelector(selector).getBoundingClientRect()
      return [rect.x, rect.y, rect.width, rect.height]
    }))
    const scrollState = await page.locator('.questionnaire-stage-card > .el-card__body[aria-label="问卷内容"]').evaluate((body) => {
      body.scrollTop = Math.min(160, body.scrollHeight - body.clientHeight)
      const area = body.closest('.onboarding-page').closest('.content-area')
      return { scrollTop: body.scrollTop, scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,
        overflowY: getComputedStyle(body).overflowY, containedLayout: document.querySelector('.onboarding-page').classList.contains('is-contained-layout'),
        ariaLabel: body.getAttribute('aria-label'), areaTop: area.scrollTop, questionCount: document.querySelectorAll('.question-block').length,
        windowY: window.scrollY, documentTop: document.scrollingElement.scrollTop }
    })
    assert.ok(scrollState.scrollHeight > scrollState.clientHeight && scrollState.scrollTop > 0, `long questionnaire should scroll inside its labelled card region: ${JSON.stringify(scrollState)}`)
    assert.equal(scrollState.containedLayout, true, 'the questionnaire must retain the validated contained layout')
    assert.equal(scrollState.ariaLabel, '问卷内容')
    assert.equal(scrollState.areaTop, 0, 'questionnaire body scrolling must leave the app content area at the top')
    assert.equal(scrollState.windowY, 0, 'questionnaire scroll must keep the document fixed')
    assert.equal(scrollState.documentTop, 0, 'questionnaire scroll must keep document scrollTop fixed')
    const shellAfterScroll = await page.evaluate(() => ['.sidebar', '.topbar'].map((selector) => {
      const rect = document.querySelector(selector).getBoundingClientRect()
      return [rect.x, rect.y, rect.width, rect.height]
    }))
    assert.deepEqual(shellAfterScroll, shellBeforeScroll, 'inner questionnaire scrolling must leave the fixed shell stationary')
    note('onboarding-directional-module-motion', { scrollTop: scrollState.scrollTop, documentTop: scrollState.documentTop, areaTop: scrollState.areaTop, containedLayout: scrollState.containedLayout })
    await context.close()
  } finally { activeContexts.delete(context) }
}

async function testHistoryAndReportModules() {
  const history = await createPage('/learning/history')
  try {
    const { page, context } = history
    await page.locator('.profile-item').filter({ hasText: '画像 A' }).waitFor()
    await page.getByText('节点 A', { exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.journey-workspace')?.hasAttribute('data-motion-running'))
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    const beforeCount = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.journey-workspace')).length)
    await page.locator('.profile-item').filter({ hasText: '画像 B' }).click()
    await page.getByText('节点 B', { exact: true }).waitFor()
    const sample = await waitForModuleMotion(page, '.journey-workspace', 0)
    assert.equal(sample.transform, 'none', 'history module motion should fade without moving its scroll region')
    assert.ok(sample.opacity > 0.5 && sample.opacity < 1)
    const afterCount = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.journey-workspace')).length)
    assert.ok(afterCount > beforeCount)
    summary.moduleAnimations.push(sample)
    await writeScreenshot(page, 'history-profile-module-midpoint')
    await resumeSampledAnimation(page)
    note('history-profile-module-fade')
    await context.close()
  } finally { activeContexts.delete(history.context) }

  const report = await createPage('/report')
  try {
    const { page, context } = report
    await page.locator('.summary-metric strong').first().filter({ hasText: '107' }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.report-summary-metrics')?.hasAttribute('data-motion-running'))
    await page.evaluate(() => {
      window.__motionAudit.pauseModules = true
      window.__reportMetrics = document.querySelector('.report-summary-metrics')
      window.__masterySection = document.querySelector('.report-mastery-section')
      window.__otherCharts = ['.report-radar-slot', '.report-fit-slot', '.report-path-slot']
        .map((selector) => document.querySelector(`${selector} > *`))
    })
    await page.locator('.report-window-field .el-select__wrapper').click()
    await page.getByRole('option', { name: '近 7 天' }).click()
    await page.waitForFunction(() => document.querySelector('.report-summary-metrics')?.getAttribute('data-motion-running') === 'module')
    const sample = await page.evaluate(() => {
      const element = document.querySelector('.report-summary-metrics')
      const animation = element.getAnimations().find((item) => item.effect?.target === element)
      if (!animation) return null
      const timing = animation.effect.getTiming(); animation.pause(); animation.currentTime = Number(timing.duration) * 0.25
      const style = getComputedStyle(element)
      window.__motionAudit.lastSample = animation
      return { selector: '.report-summary-metrics', durationMs: Number(timing.duration), easing: timing.easing, keyframes: animation.effect.getKeyframes(), opacity: Number(style.opacity), transform: style.transform }
    })
    assert.ok(sample && sample.opacity > 0.5 && sample.opacity < 0.95, 'report window change should fade the summary module through an intermediate frame')
    assert.equal(sample.durationMs, 200, 'report window fade must use the actual 200ms WAAPI duration')
    assert.equal(sample.easing, expectedMotionEasing, 'report window fade must use the shared easing')
    assert.equal(sample.transform, 'none', 'report summary motion must not transform the chart or scroll region')
    summary.moduleAnimations.push(sample)
    await writeScreenshot(page, 'report-window-module-midpoint')
    await resumeSampledAnimation(page)
    await page.waitForFunction(() => !document.querySelector('.report-summary-metrics')?.hasAttribute('data-motion-running'))

    const animationCount = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.report-summary-metrics')).length)
    const transitionCount = await page.evaluate(() => window.__motionAudit.starts)
    const stream = [...reportStreams].find((item) => item.learnerId === 'learner-A' && item.windowDays === 7)
    assert.ok(stream, 'the current report window should have an open fixture event stream')
    reportRevision += 1
    reportResourceCount = 207
    stream.response.write(`event: report_changed\ndata: ${JSON.stringify({ learner_id: 'learner-A', window_days: 7, report_revision: fixtureReport(7).report_revision })}\n\n`)
    await page.getByText('207', { exact: true }).waitFor()
    const animationCountAfterSse = await page.evaluate(() => window.__motionAudit.animations.filter((item) => item.element.matches('.report-summary-metrics')).length)
    assert.equal(animationCountAfterSse, animationCount, 'SSE data refresh must not replay the window-change fade')
    const chartWrappersStable = await page.evaluate(() => window.__masterySection === document.querySelector('.report-mastery-section')
      && window.__otherCharts.every((element, index) => element === document.querySelector(`${['.report-radar-slot', '.report-fit-slot', '.report-path-slot'][index]} > *`)))
    assert.equal(chartWrappersStable, true, 'SSE refresh must preserve the surrounding chart regions and non-keyed chart roots')
    const afterSseMotion = await page.evaluate(() => ({
      transitions: window.__motionAudit.starts,
      pageMotion: document.documentElement.hasAttribute('data-page-motion'),
      runningMotion: document.querySelectorAll('[data-motion-running]').length,
      moduleAnimations: window.__motionAudit.animations.filter((item) => item.element.hasAttribute('data-motion-module')).length,
    }))
    assert.equal(afterSseMotion.transitions, transitionCount, 'SSE data refresh must not create a page snapshot transition')
    assert.equal(afterSseMotion.pageMotion, false, 'SSE data refresh must not enter page-transition state')
    assert.equal(afterSseMotion.runningMotion, 0, 'SSE data refresh must not leave motion running')
    assert.equal(afterSseMotion.moduleAnimations, animationCount, 'SSE data refresh must not replay the window module fade')
    assert.equal(await page.evaluate(() => window.__reportMetrics === document.querySelector('.report-summary-metrics')), true, 'report animation must retain the live summary module')
    note('report-window-fade-and-sse-stability', { animationCount, animationCountAfterSse, chartWrappersStable, afterSseMotion })
    await context.close()
  } finally { activeContexts.delete(report.context) }
}

async function testReducedMotionAndNativeFailure() {
  const reduced = await createPage('/dashboard', { reducedMotion: 'reduce' })
  try {
    const { page, context } = reduced
    await waitForPage(page, '.home-page')
    await page.locator('.topbar-actions .el-button:has-text("学习历史")').click()
    await page.waitForFunction(() => location.pathname === '/learning/history')
    await waitForPage(page, '.history-page')
    const state = await page.evaluate(() => ({
      starts: window.__motionAudit.starts, running: document.querySelectorAll('[data-motion-running]').length,
      pageMotion: document.documentElement.hasAttribute('data-page-motion'), preference: matchMedia('(prefers-reduced-motion: reduce)').matches,
    }))
    assert.equal(state.preference, true)
    assert.equal(state.starts, 0, 'startup reduced-motion must bypass native view transitions')
    assert.equal(state.running, 0, 'startup reduced-motion must bypass WAAPI motion')
    assert.equal(state.pageMotion, false)
    note('reduced-motion-at-startup', state)
    await context.close()
  } finally { activeContexts.delete(reduced.context) }

  const throwing = await createPage('/dashboard', { apiMode: 'throw' })
  try {
    const { page, context } = throwing
    await waitForPage(page, '.home-page')
    await page.addStyleTag({ content: ':root{--motion-fallback-exit:180ms;--motion-page-enter:180ms}' })
    await page.locator('.topbar-actions .el-button:has-text("学习历史")').click()
    await page.waitForFunction(() => location.pathname === '/learning/history')
    await waitForPage(page, '.history-page')
    assert.equal(await page.evaluate(() => window.__motionAudit.starts), 1, 'a native start exception should be caught and fall back')
    await checkNoResidue(page, 'native-start-throws')
    note('native-start-throws-fallback')
    await context.close()
  } finally { activeContexts.delete(throwing.context) }

  const runtime = await createPage('/learning/new')
  try {
    const { page, context } = runtime
    await page.locator('.domain-stage-card .choice-card').first().waitFor()
    await page.evaluate(() => { window.__motionAudit.pauseModules = true })
    const before = await page.evaluate(() => window.__motionAudit.animations.length)
    await page.locator('.domain-stage-card .choice-card').first().click()
    await page.getByRole('button', { name: '下一步' }).click()
    await page.locator('.track-stage-card').waitFor()
    await waitForModuleMotion(page, '.step-panel', before)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.waitForFunction(() => !document.querySelector('.step-panel')?.hasAttribute('data-motion-running'))
    assert.equal(await page.evaluate(() => document.querySelectorAll('[data-motion-running]').length), 0, 'runtime preference change must cancel active module animation')
    assert.equal(await page.evaluate(() => document.querySelector('.track-stage-card') !== null), true, 'canceling animation must leave navigation content usable')
    note('runtime-reduced-motion-cancels-waapi')
    await context.close()
  } finally { activeContexts.delete(runtime.context) }

  const nativeRuntime = await createPage('/dashboard')
  try {
    const { page, context } = nativeRuntime
    await waitForPage(page, '.home-page')
    await page.addStyleTag({ content: ':root{--motion-page-enter:900ms;--motion-page-exit:900ms}' })
    const navigation = page.waitForFunction(() => location.pathname === '/learning/history')
    await page.locator('.topbar-actions .el-button:has-text("学习历史")').click()
    await page.waitForFunction(() => getComputedStyle(document.documentElement, '::view-transition-new(app-page)').animationName.includes('page-arrive'))
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await navigation
    await waitForPage(page, '.history-page')
    await checkNoResidue(page, 'runtime-reduced-native')
    note('runtime-reduced-motion-skips-native-transition')
    await context.close()
  } finally { activeContexts.delete(nativeRuntime.context) }
}

try {
  browser = await chromium.launch(browserOptions('MOTION_BROWSER_CHANNEL'))
  await caseRun('native-navigation', testNativeNavigation)
  await caseRun('auth-form-local-motion', testAuthModeMotion)
  await caseRun('fallback-no-native-api', () => testFallback('disabled', 'api-disabled'))
  await caseRun('fallback-native-start-throws', () => testFallback('throw', 'api-throws'))
  await caseRun('rapid-navigation-history', testRapidNavigationAndHistory)
  await caseRun('resource-query-and-focus-reuse', testResourceReuse)
  await caseRun('onboarding-modules', testOnboardingModules)
  await caseRun('history-report-modules', testHistoryAndReportModules)
  await caseRun('reduced-motion-native-failure', testReducedMotionAndNativeFailure)

  assert.deepEqual(summary.externalRequests, [], 'browser fixture must not reach external hosts')
  assert.deepEqual(summary.writes, [], 'browser fixture must not receive business write requests')
  assert.deepEqual(summary.unexpectedApi, [], 'browser fixture must define every requested API endpoint')
  assert.deepEqual(summary.pageErrors, [], 'browser pages must not raise uncaught exceptions')
  assert.deepEqual(summary.unhandledRejections, [], 'browser pages must not leave unhandled Promise rejections')
  assert.deepEqual(summary.failures, [], 'every motion browser scenario must pass')
  summary.status = 'PASS'
} catch (error) {
  summary.status = 'FAIL'
  summary.error = String(error?.stack || error)
  throw error
} finally {
  for (const stream of reportStreams) { try { stream.response.end() } catch {} }
  reportStreams.clear()
  for (const context of activeContexts) { try { await context.close() } catch {} }
  activeContexts.clear()
  if (browser) await browser.close()
  await new Promise((resolve) => server.close(resolve))
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + '\n', 'utf8')
}

console.log(JSON.stringify({ status: summary.status, checks: summary.checks, screenshots: summary.screenshots, evidence: summaryPath }, null, 2))
