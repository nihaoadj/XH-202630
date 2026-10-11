import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'report-ui')
const summaryPath = path.join(evidenceDir, 'summary.json')
if (!existsSync(path.join(distDir, 'index.html'))) throw new Error('先运行 npm --prefix frontend run build，再执行报告页浏览器验收')
mkdirSync(evidenceDir, { recursive: true })

const audit = { requests: [], writes: [], unexpectedApi: [], externalRequests: [], pageErrors: [] }
const summary = { status: 'RUNNING', evidence_type: 'browser_fixture', screenshots: [], checks: [], layouts: [], chartOptions: {}, audit }
const longDirectionName = '临床数据分析与循证护理整合实践方向（覆盖急诊评估、证据核验、风险沟通及跨学科处置）'
const longSuggestion = '先复核高风险情境中的证据来源与适用条件，再完成结构化风险分层练习，并逐项记录处置依据、复核时间和交接对象。'
const profileFixtures = [
  { learner_id: 'learner-main', learner_type: '主学习画像', knowledge_base_id: 'kb-main', skill_level: '进阶', learning_goal: '准确完成高风险临床问题的证据检索与处置', learning_preferences: { metadata: { user_profile_snapshot: { display_name: '主学习画像' } } } },
  { learner_id: 'learner-calibration', learner_type: '初始校准画像', knowledge_base_id: 'kb-calibration', skill_level: '初级', learning_goal: '完成初始能力诊断', learning_preferences: { metadata: { user_profile_snapshot: { display_name: '初始校准画像' } } } },
]
const tracks = [{ track_id: 'kb-main', name: longDirectionName }, { track_id: 'kb-calibration', name: '初始诊断方向' }]
const nodeNames = ['风险评估与分层决策', '临床证据检索', '跨学科路径协调', '急诊沟通与交接', '治疗反应观察', '核心并发症识别', '指南适用条件核验', '患者安全事件处置', '质量改进与复盘', '证据链追溯与验证']
const masteryNodes = nodeNames.map((name, index) => {
  const status = ['weak', 'learning', 'mastered', 'self_reported', 'unassessed'][index % 5]
  const measured = status !== 'unassessed'
  const scores = [0.38, 0.66, 0.92, 0.74]
  return {
    skill_node_id: 'mastery-' + (index + 1), name, tier: index % 3 + 1,
    mastery_score: measured ? scores[index % 4] : null,
    latest_observed_score: measured ? Math.max(0, scores[index % 4] - 0.04) : null,
    mastery_status: status,
    conclusion: status === 'unassessed' ? 'unassessed' : status === 'mastered' ? 'confirmed_mastery' : 'awaiting_confirmation',
    next_action: status === 'weak' ? 'remediate' : status === 'mastered' ? 'maintain' : 'verify',
    independent_session_count: measured ? index % 3 + 1 : 0,
    objective_evidence_count: measured ? index % 4 + 1 : 0,
  }
})
const resourcePoints = [
  { resource_id: 'resource-1', resource_name: '急诊风险评估与安全处置学习讲义', skill_node_id: 'mastery-1', skill_name: nodeNames[0], resource_type: '讲义', learner_readiness_score: 0.42, resource_difficulty_score: 0.65, difficulty_gap: 0.23, match_status: 'challenging', confidence: 'high', difficulty_source: 'declared_band', credibility_score: 86, credibility_level: 'high', credibility_grade: 'trusted', credibility_score_breakdown: { publication_review_score: 36, source_traceability_score: 43, claim_review_score: 7, claim_review_passed: true, ceiling_applied: false } },
  { resource_id: 'resource-2', resource_name: '循证资源核验要点', skill_node_id: 'mastery-2', skill_name: nodeNames[1], resource_type: '案例', learner_readiness_score: 0.58, resource_difficulty_score: 0.61, difficulty_gap: 0.03, match_status: 'matched', confidence: 'medium', difficulty_source: 'declared_band', credibility_score: 80, credibility_level: 'good', credibility_grade: 'trusted', credibility_score_breakdown: { publication_review_score: 40, source_traceability_score: 50, claim_review_score: 0, claim_review_passed: false, score_ceiling: 80, ceiling_applied: true } },
  { resource_id: 'resource-3', resource_name: '跨专业路径协同', skill_node_id: 'mastery-3', skill_name: nodeNames[2], resource_type: '练习', learner_readiness_score: null, resource_difficulty_score: 0.76, difficulty_gap: null, match_status: 'not_measured', confidence: 'low', difficulty_source: 'declared_band', credibility_score: null, credibility_level: 'insufficient_evidence', credibility_grade: 'unavailable', credibility_score_breakdown: null },
  { resource_id: 'resource-4', resource_name: '临床交接结构化练习', skill_node_id: 'mastery-4', skill_name: nodeNames[3], resource_type: '讲义', learner_readiness_score: 0.7, resource_difficulty_score: null, difficulty_gap: null, match_status: 'not_measured', confidence: 'low', difficulty_source: 'declared_band', credibility_score: 72, credibility_level: 'moderate', credibility_grade: 'reviewed', credibility_score_breakdown: { publication_review_score: 35, source_traceability_score: 37, claim_review_score: 0, claim_review_passed: false, score_ceiling: 80, ceiling_applied: false } },
  { resource_id: 'resource-5', resource_name: '处置后观察与复盘', skill_node_id: 'mastery-5', skill_name: nodeNames[4], resource_type: '案例', learner_readiness_score: 0.77, resource_difficulty_score: 0.73, difficulty_gap: -0.04, match_status: 'matched', confidence: 'high', difficulty_source: 'calibrated_history', feedback_score: 0.82, difficulty_adjustment: 0.08, default_resource_difficulty_score: 0.65, credibility_score: 91, credibility_level: 'high', credibility_grade: 'trusted', credibility_score_breakdown: { publication_review_score: 40, source_traceability_score: 45, claim_review_score: 6, claim_review_passed: true, ceiling_applied: false } },
  { resource_id: 'resource-6', resource_name: '并发症风险复核', skill_node_id: 'mastery-6', skill_name: nodeNames[5], resource_type: '练习', learner_readiness_score: 0.62, resource_difficulty_score: 0.58, difficulty_gap: -0.04, match_status: 'matched', confidence: 'medium', difficulty_source: 'declared_band', credibility_score: 77, credibility_level: 'moderate', credibility_grade: 'reviewed', credibility_score_breakdown: { publication_review_score: 39, source_traceability_score: 38, claim_review_score: 0, claim_review_passed: false, ceiling_applied: false } },
]
const pathNodes = [
  { skill_node_id: 'path-prerequisite', name: '基础知识回顾', tier: 1, stable_order: 1, role: 'prerequisite', progress_status: 'completed', mastery_score: 0.88 },
  { skill_node_id: 'path-current', name: '风险评估与分层决策', tier: 2, stable_order: 1, role: 'current', progress_status: 'learning', is_current_batch: true, mastery_score: 0.62 },
  { skill_node_id: 'path-remedial', name: '证据检索与质量核验', tier: 2, stable_order: 2, role: 'remedial', progress_status: 'reinforcement_due', mastery_score: 0.43 },
  { skill_node_id: 'path-next', name: '协同路径规划', tier: 3, stable_order: 1, role: 'next', progress_status: 'unlocked', blocked: false },
  { skill_node_id: 'path-locked', name: '高风险病例复盘', tier: 4, stable_order: 1, role: 'challenge', progress_status: 'locked', blocked: true, blocked_by_node_ids: ['path-next'] },
]
const states = new Map()
const sseClients = new Set()
let fixtureMode = 'full'
let forceNextUpdate = false
function reportKey(learnerId, days) { return learnerId + ':' + days }
function revision(learnerId, days, version) { return 'rpt-' + learnerId + '-' + days + '-v' + version }
function makeReport(learnerId, days, pending = false) {
  const state = { version: 1, data: null }
  const empty = pending
  state.data = {
    report_schema_version: '3.0', report_revision: revision(learnerId, days, state.version), learner_id: learnerId,
    generated_at: '2026-10-09T02:00:00Z', as_of_profile_version: 4, skill_level: empty ? '初级' : '进阶',
    learning_goal: empty ? '完成初始能力诊断' : '准确完成高风险临床问题的证据检索与处置',
    radar: empty ? { dimensions: [], values: [], measurement_statuses: [] } : {
      dimensions: ['风险识别', '证据核验', '协同决策', '沟通交接', '质量复盘'],
      values: [82, 69, 76, 64, 90], measurement_statuses: ['measured', 'self_reported', 'unassessed', 'measured', 'measured'],
    },
    weak_points: empty ? [] : ['证据检索与质量核验'], strong_points: empty ? [] : ['质量复盘'], difficulty_curve: [],
    metric_summary: empty ? { resource_count: 0, feedback_count: 0, average_correct_rate: null, weak_point_count: 0 } : { resource_count: 16, feedback_count: 23, average_correct_rate: 0.74, weak_point_count: 4 },
    learning_activity: empty ? { status: 'not_measured', verified_attempt_count: 0, answered_item_count: 0, correct_item_count: 0, verified_accuracy: null, accuracy_delta: null } : { status: 'measured', verified_attempt_count: 19, answered_item_count: 26, correct_item_count: 19, verified_accuracy: 0.74, accuracy_delta: 0.08 },
    weakness_groups: { verified_weak: [], regressing_learning: [], needs_evidence: [] },
    resource_credibility_summary: { total_count: empty ? 0 : 6, trusted_count: empty ? 0 : 4 },
    recent_resource_credibility: [], ability_nodes: [], mastery_summary: {}, weakness_priorities: [], recent_resources: [], recent_feedback: [],
    next_suggestions: empty ? [] : ['巩固风险分层的核心判定条件', longSuggestion, '完成一轮循证核验与结构化交接练习'],
    initial_diagnostic: empty ? null : { questionnaire_tier: 3, final_tier: 2, downgraded: true },
    report_availability: empty
      ? { status: 'calibration_pending', message: '初始能力诊断尚未完成。完成问卷和客观测评后，系统会重新校准方向与画像等级，再生成正式学习结论。' }
      : { status: 'available', message: '报告数据已更新' },
    learning_node_mastery_map: { schema_version: '1.0', nodes: empty ? [] : masteryNodes, summary: { total_node_count: empty ? 0 : masteryNodes.length, measured_node_count: empty ? 0 : masteryNodes.filter((node) => typeof node.mastery_score === 'number').length } },
    resource_difficulty_curve: {
      schema_version: '1.0', strategy_version: 'declared-band/calibrated-history', points: empty ? [] : resourcePoints,
      summary: empty ? {} : { total_point_count: 6, measured_point_count: 4, total_resource_count: 6, credibility_scored_count: 5, average_credibility_score: 81, claim_review_passed_count: 2, claim_ceiling_applied_count: 1 },
    },
    learning_path_graph: {
      schema_version: '1.0', nodes: empty ? [] : pathNodes,
      edges: empty ? [] : [
        { source_skill_node_id: 'path-prerequisite', target_skill_node_id: 'path-current' },
        { source_skill_node_id: 'path-current', target_skill_node_id: 'path-next' },
        { source_skill_node_id: 'path-remedial', target_skill_node_id: 'path-next' },
        { source_skill_node_id: 'path-next', target_skill_node_id: 'path-locked' },
      ],
      focus_node_ids: empty ? [] : ['path-current', 'path-remedial', 'path-next'],
      current_node_ids: empty ? [] : ['path-current'], recommended_next_node_ids: empty ? [] : ['path-remedial', 'path-next'],
      summary: empty ? {} : { eligible_remedial_node_count: 1, verification_node_count: 2, next_node_count: 1, blocked_node_count: 1 },
    },
    window: { window_days: days }, freshness: { source_revisions: { learning: 9, resources: 6, feedback: 14 } },
  }
  return state
}
function getReportState(learnerId, days) {
  const key = reportKey(learnerId, days)
  if (!states.has(key)) states.set(key, makeReport(learnerId, days, learnerId === 'learner-calibration'))
  return states.get(key)
}
function sendJson(response, body, status = 200, headers = {}) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers })
  response.end(status === 304 ? '' : JSON.stringify(body))
}
function auditRequest(request, url, body) {
  const item = { method: (request.method || 'GET').toUpperCase(), path: url.pathname, query: url.search, body, ifNoneMatch: request.headers['if-none-match'] || null, responseStatus: 200 }
  audit.requests.push(item)
  if (item.method !== 'GET' && item.method !== 'HEAD') { item.allowed = false; audit.writes.push(item) }
  return item
}
function sendEvent(response, name, data) { response.write('event: ' + name + '\ndata: ' + JSON.stringify(data) + '\n\n') }
function emitChanged(learnerId, days) {
  const state = getReportState(learnerId, days)
  state.version += 1
  state.data = structuredClone(state.data)
  state.data.report_revision = revision(learnerId, days, state.version)
  state.data.metric_summary.resource_count += 2
  state.data.generated_at = '2026-10-09T02:15:00Z'
  const event = { learner_id: learnerId, window_days: days, report_revision: state.data.report_revision }
  for (const client of sseClients) if (client.learnerId === learnerId && client.days === days && !client.response.destroyed) sendEvent(client.response, 'report_changed', event)
  return state.data.metric_summary.resource_count
}

function allowedApi(method, pathname) {
  return method === 'GET' && (
    pathname === '/api/auth/me'
    || pathname === '/api/profiles/'
    || pathname === '/api/knowledge/domains'
    || /^\/api\/report\/[^/]+(?:\/events)?$/.test(pathname)
    || pathname === '/api/skills/nodes'
    || /^\/api\/resource-library\/learner-[a-z0-9-]+$/.test(pathname)
    || pathname === '/api/generate/jobs'
    || pathname === '/api/resources/courseware/jobs'
    || /^\/api\/learning-history\/[^/]+\/journey$/.test(pathname)
  )
}
const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://127.0.0.1')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    let rawBody = ''
    for await (const chunk of request) rawBody += chunk
    let body = null
    if (rawBody) { try { body = JSON.parse(rawBody) } catch { body = rawBody } }
    const item = auditRequest(request, url, body)
    if (!allowedApi(method, url.pathname)) {
      audit.unexpectedApi.push({ method, path: url.pathname, query: url.search })
      return sendJson(response, { detail: 'Unexpected report UI fixture API request' }, 404)
    }
    if (url.pathname === '/api/auth/me') return sendJson(response, { user: { user_id: 'report-ui-user', username: 'report.fixture', display_name: '报告验收用户' } })
    if (url.pathname === '/api/profiles/') {
      const items = fixtureMode === 'empty-profiles' ? [] : profileFixtures
      return sendJson(response, { items, total: items.length })
    }
    if (url.pathname === '/api/knowledge/domains') return sendJson(response, { domains: [{ domain_id: 'domain-report', tracks }] })
    if (url.pathname === '/api/skills/nodes') return sendJson(response, { nodes: [] })
    if (/^\/api\/resource-library\/learner-[a-z0-9-]+$/.test(url.pathname)) return sendJson(response, [])
    if (url.pathname === '/api/generate/jobs') return sendJson(response, { items: [], total: 0 })
    if (url.pathname === '/api/resources/courseware/jobs') return sendJson(response, { items: [], total: 0 })
    const historyMatch = url.pathname.match(/^\/api\/learning-history\/([^/]+)\/journey$/)
    if (historyMatch) {
      const learnerId = decodeURIComponent(historyMatch[1])
      const profile = profileFixtures.find((entry) => entry.learner_id === learnerId) || profileFixtures[0]
      return sendJson(response, {
        learner_id: learnerId, profile,
        current_state: { current_nodes: [], completed_nodes: [], next_action: null, latest_assessment: null },
        rounds: [], unlinked_events: [], total_rounds: 0, next_offset: null,
      })
    }
    const eventMatch = url.pathname.match(/^\/api\/report\/([^/]+)\/events$/)
    if (eventMatch) {
      const learnerId = decodeURIComponent(eventMatch[1])
      const days = Number(url.searchParams.get('window_days') || 30)
      const state = getReportState(learnerId, days)
      response.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache, no-transform', connection: 'keep-alive', 'x-accel-buffering': 'no' })
      const client = { learnerId, days, response }
      sseClients.add(client)
      response.on('close', () => sseClients.delete(client))
      sendEvent(response, 'report_snapshot', { learner_id: learnerId, window_days: days, report_revision: state.data.report_revision })
      return
    }
    const reportMatch = url.pathname.match(/^\/api\/report\/([^/]+)$/)
    if (reportMatch) {
      const learnerId = decodeURIComponent(reportMatch[1])
      const days = Number(url.searchParams.get('window_days') || 30)
      const state = getReportState(learnerId, days)
      if (forceNextUpdate && !item.ifNoneMatch) {
        forceNextUpdate = false
        state.version += 1
        state.data = structuredClone(state.data)
        state.data.report_revision = revision(learnerId, days, state.version)
        state.data.metric_summary.resource_count += 1
        state.data.generated_at = '2026-10-09T02:10:00Z'
      }
      const etag = '"' + state.data.report_revision + '"'
      if (item.ifNoneMatch === etag) {
        item.responseStatus = 304
        return sendJson(response, null, 304, { etag })
      }
      return sendJson(response, state.data, 200, { etag })
    }
    return sendJson(response, { detail: 'Fixture handler missing' }, 404)
  }
  const candidate = path.resolve(distDir, '.' + decodeURIComponent(url.pathname))
  const prefix = distDir.endsWith(path.sep) ? distDir : distDir + path.sep
  let file = candidate.startsWith(prefix) || candidate === path.join(distDir, 'index.html') ? candidate : path.join(distDir, 'index.html')
  if (!existsSync(file)) file = path.join(distDir, 'index.html')
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff': 'font/woff; charset=utf-8', '.woff2': 'font/woff2', '.ico': 'image/x-icon' }
  response.writeHead(200, { 'content-type': types[path.extname(file).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-cache' })
  response.end(readFileSync(file))
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const baseUrl = 'http://127.0.0.1:' + server.address().port
const browser = await chromium.launch(browserOptions('REPORT_UI_BROWSER_CHANNEL'))
const context = await browser.newContext()
context.setDefaultTimeout(8000)
context.setDefaultNavigationTimeout(15000)
const pages = new Set()

async function newPage({ width, height, collapsed = false, reducedMotion = false }) {
  const page = await context.newPage()
  await page.setViewportSize({ width, height })
  page.on('pageerror', (error) => audit.pageErrors.push({ message: error.message, url: page.url() }))
  page.on('request', (request) => {
    const url = request.url()
    if (/^https?:/.test(url) && new URL(url).origin !== new URL(baseUrl).origin) audit.externalRequests.push(url)
  })
  await page.route('**/*', async (route) => {
    const url = route.request().url()
    if (/^https?:/.test(url) && new URL(url).origin !== new URL(baseUrl).origin) {
      audit.externalRequests.push(url)
      return route.abort()
    }
    return route.continue()
  })
  await page.addInitScript((isCollapsed) => {
    localStorage.clear()
    localStorage.setItem('app_sidebar_collapsed', String(isCollapsed))
  }, collapsed)
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' })
  pages.add(page)
  return page
}
async function openReport({ width = 1393, height = 871, collapsed = false, reducedMotion = false } = {}) {
  const page = await newPage({ width, height, collapsed, reducedMotion })
  await page.goto(baseUrl + '/report', { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '学习报告', level: 2 }).waitFor()
  await page.locator('.report-page').waitFor()
  await page.locator('.report-focus strong').waitFor()
  await page.getByText('平均可信度', { exact: false }).waitFor()
  await waitForCharts(page)
  await page.waitForTimeout(1300)
  return page
}
const chartSelectors = {
  mastery: 'article[aria-labelledby="node-mastery-heading"] .chart',
  radar: '.chart-card .chart',
  difficulty: 'article[aria-labelledby="difficulty-heading"] .chart',
  path: 'article[aria-labelledby="path-graph-heading"] .chart',
}
async function readChartOptions(page, tolerateMissing = false) {
  const options = await page.evaluate((selectors) => {
    const targets = new Map()
    for (const [name, selector] of Object.entries(selectors)) {
      const element = document.querySelector(selector)
      if (element) targets.set(element, name)
    }
    const raw = {}
    const seen = new Set()
    function visit(vnode) {
      if (!vnode || typeof vnode !== 'object' || seen.has(vnode)) return
      seen.add(vnode)
      const instance = vnode.component
      if (instance) {
        const setup = instance.setupState || {}
        if (setup.root && targets.has(setup.root) && typeof setup.getOption === 'function') raw[targets.get(setup.root)] = setup.getOption()
        visit(instance.subTree)
      }
      if (vnode.suspense) { visit(vnode.suspense.activeBranch); visit(vnode.suspense.pendingBranch) }
      if (Array.isArray(vnode.children)) for (const child of vnode.children) visit(child)
    }
    visit(document.querySelector('#app')?._vnode)
    const array = (value) => Array.isArray(value) ? value : value ? [value] : []
    const series = (option) => array(option.series).map((item) => ({
      type: item.type, name: item.name || null, roam: item.roam ?? null,
      lineColor: item.lineStyle?.color || null,
      lineWidth: item.lineStyle?.width ?? null,
      itemColor: typeof item.itemStyle?.color === 'string' ? item.itemStyle.color : null,
      areaColor: item.areaStyle?.color ?? null,
      symbolSize: item.symbolSize ?? null,
      labelStyle: item.label ? {
        show: item.label.show ?? null, color: item.label.color ?? null,
        fontSize: item.label.fontSize ?? null, fontWeight: item.label.fontWeight ?? null,
        width: item.label.width ?? null, overflow: item.label.overflow ?? null,
      } : null,
      data: array(item.data).map((datum) => ({
        name: datum?.name || null,
        value: datum && typeof datum === 'object' ? (datum.value ?? null) : datum ?? null,
        color: typeof datum?.itemStyle?.color === 'string' ? datum.itemStyle.color : null,
        opacity: datum?.itemStyle?.opacity ?? null,
        label: typeof datum?.label?.formatter === 'string' ? datum.label.formatter : null,
        labelStyle: datum?.label ? {
          show: datum.label.show ?? null, color: datum.label.color ?? null, fontSize: datum.label.fontSize ?? null,
          fontWeight: datum.label.fontWeight ?? null, width: datum.label.width ?? null, overflow: datum.label.overflow ?? null,
        } : null,
        learningState: datum?.learningState || null,
      })),
      links: array(item.links).map((link) => ({ source: link.source, target: link.target, color: link.lineStyle?.color || null, width: link.lineStyle?.width ?? null, opacity: link.lineStyle?.opacity ?? null })),
      symbol: item.symbol || null, dataCount: array(item.data).length,
    }))
    const axes = (value) => array(value).map((axis) => ({
      type: axis.type || null, min: axis.min ?? null, max: axis.max ?? null, data: array(axis.data), inverse: axis.inverse ?? false,
      labelStyle: axis.axisLabel ? {
        color: axis.axisLabel.color ?? null, fontSize: axis.axisLabel.fontSize ?? null,
        width: axis.axisLabel.width ?? null, overflow: axis.axisLabel.overflow ?? null,
      } : null,
    }))
    const summarize = (option) => ({
      series: series(option),
      radarIndicators: array(option.radar).flatMap((radar) => array(radar.indicator).map((item) => ({ name: item.name, max: item.max }))),
      radarAxisName: array(option.radar).map((radar) => ({ color: radar.axisName?.color ?? null, fontSize: radar.axisName?.fontSize ?? null })),
      xAxis: axes(option.xAxis), yAxis: axes(option.yAxis),
      dataZoom: array(option.dataZoom).map((item) => ({ type: item.type, start: item.start, end: item.end, xAxisIndex: item.xAxisIndex ?? null, yAxisIndex: item.yAxisIndex ?? null })),
      legend: array(option.legend).map((item) => ({ type: item.type || null, data: array(item.data), textStyle: { color: item.textStyle?.color ?? null, fontSize: item.textStyle?.fontSize ?? null } })),
    })
    return Object.fromEntries(Object.entries(raw).map(([name, option]) => [name, summarize(option)]))
  }, chartSelectors)
  if (!tolerateMissing) assert.deepEqual(Object.keys(options).sort(), Object.keys(chartSelectors).sort(), '必须从 ECharts 实例 getOption() 读取四图')
  return options
}
async function readPathGraphLayout(page) {
  return page.evaluate(() => {
    const target = document.querySelector('.report-path-slot .chart')
    let chart = null
    const seen = new Set()
    function visit(vnode) {
      if (!vnode || typeof vnode !== 'object' || seen.has(vnode) || chart) return
      seen.add(vnode)
      const instance = vnode.component
      if (instance) {
        const setup = instance.setupState || {}
        if (setup.root === target && typeof setup.getOption === 'function') {
          const candidate = setup.chart?.value || setup.chart
          if (candidate && typeof candidate.getModel === 'function') chart = candidate
        }
        visit(instance.subTree)
      }
      if (vnode.suspense) { visit(vnode.suspense.activeBranch); visit(vnode.suspense.pendingBranch) }
      if (Array.isArray(vnode.children)) for (const child of vnode.children) visit(child)
    }
    visit(document.querySelector('#app')?._vnode)
    const data = chart?.getModel?.().getSeriesByIndex(0)?.getData?.()
    const option = chart?.getOption?.().series?.[0]
    const transformedBounds = (element) => {
      if (!element?.getBoundingRect || !element?.getComputedTransform) return null
      const matrix = element.getComputedTransform() || [1, 0, 0, 1, 0, 0]
      const rect = element.getBoundingRect()
      const points = [[rect.x, rect.y], [rect.x + rect.width, rect.y], [rect.x, rect.y + rect.height], [rect.x + rect.width, rect.y + rect.height]]
        .map(([x, y]) => [matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]])
      const xs = points.map(([x]) => x), ys = points.map(([, y]) => y)
      const left = Math.min(...xs), top = Math.min(...ys), right = Math.max(...xs), bottom = Math.max(...ys)
      return { left, top, right, bottom, width: right - left, height: bottom - top }
    }
    const nodes = []
    for (let index = 0; data && index < data.count(); index += 1) {
      const graphic = data.getItemGraphicEl(index)
      const symbolPath = graphic?.getSymbolPath?.() || graphic?.childAt?.(0)
      const label = symbolPath?.getTextContent?.()
      const datum = option?.data?.[index] || {}
      nodes.push({
        name: data.getName(index), id: datum.id || null, x: datum.x ?? null, y: datum.y ?? null,
        color: datum.itemStyle?.color || null,
        symbolBounds: transformedBounds(symbolPath), labelBounds: transformedBounds(label), labelText: label?.style?.text ?? null,
      })
    }
    return {
      chartRect: chart ? { width: chart.getWidth(), height: chart.getHeight() } : null,
      symbol: option?.symbol ?? null, symbolSize: option?.symbolSize ?? null,
      labelStyle: option?.label ? {
        show: option.label.show ?? null, color: option.label.color ?? null, fontSize: option.label.fontSize ?? null,
        fontWeight: option.label.fontWeight ?? null, width: option.label.width ?? null, overflow: option.label.overflow ?? null,
      } : null,
      roam: option?.roam ?? null, data: nodes,
    }
  })
}
function assertPathGraphVisible(layout, label) {
  assert.deepEqual(layout.symbolSize, [136, 54], label + ': 节点框保持 136×54')
  assert.equal(layout.symbol, 'roundRect', label + ': 节点保持圆角矩形')
  assert.equal(layout.roam, true, label + ': 保留用户缩放与拖动')
  assert.deepEqual(layout.labelStyle, { show: true, color: '#fff', fontSize: 12, fontWeight: 700, width: 112, overflow: 'truncate' }, label + ': 标签样式保持')
  assert.ok(layout.chartRect?.width > 0 && layout.chartRect?.height > 0, label + ': ECharts 图表尺寸可读')
  assert.ok(layout.data.length > 0, label + ': 路径图应包含节点')
  for (const node of layout.data) {
    for (const [part, bounds] of [['node frame', node.symbolBounds], ['node label', node.labelBounds]]) {
      assert.ok(bounds, `${label}: ${node.name} 缺少实际 ${part} 图元边界`)
      assert.ok(bounds.left >= -0.5 && bounds.top >= -0.5
        && bounds.right <= layout.chartRect.width + 0.5 && bounds.bottom <= layout.chartRect.height + 0.5,
      `${label}: ${node.name} 的 ${part} 超出图表可视边界 ${JSON.stringify({ bounds, chartRect: layout.chartRect })}`)
    }
    assert.equal(node.labelText, node.name, `${label}: ${node.name} 的实际图元标签应完整可读`)
  }
}
async function waitForCharts(page) {
  await page.waitForFunction(() => {
    const charts = [...document.querySelectorAll('.chart')]
    return Boolean(document.querySelector('#app')?._vnode) && charts.length >= 4 && charts.every((item) => item.offsetWidth > 0 && item.offsetHeight > 0)
  })
  const deadline = Date.now() + 5000
  while (Date.now() < deadline) {
    const options = await readChartOptions(page, true)
    if (Object.keys(options).length === 4 && Object.values(options).every((item) => item.series.length)) return
    await page.waitForTimeout(80)
  }
  throw new Error('无法从四个实际 ECharts 实例读取 getOption()')
}
function validateChartOptions(options) {
  const bar = options.mastery
  assert.equal(bar.series[0]?.type, 'bar')
  assert.equal(bar.xAxis[0]?.type, 'value')
  assert.equal(bar.xAxis[0]?.min, 0)
  assert.equal(bar.xAxis[0]?.max, 100)
  assert.deepEqual(bar.yAxis[0]?.labelStyle, { color: '#61758c', fontSize: 11, width: 82, overflow: 'truncate' }, '掌握图轴标签颜色、字号与宽度保持')
  assert.deepEqual(bar.series[0].data.slice(0, 5).map((item) => item.value), [38, 66, 92, 74, 0], '掌握图实际 ECharts series data 应为百分制 38/66/92/74/0')
  assert.deepEqual(bar.series[0].data[0]?.labelStyle, { show: true, color: '#536d87', fontSize: 11, fontWeight: null, width: null, overflow: null }, '掌握图数据标签颜色与字号保持')
  assert.ok(bar.dataZoom.some((item) => item.type === 'slider' && item.yAxisIndex === 0), '掌握图应保留节点 slider zoom')
  assert.ok(bar.series[0].data.some((item) => item.value === 0 && item.color === '#b8c3cf' && item.opacity === 0.35 && item.label === '待测'), '未测节点应保留灰色待测语义')
  for (const color of ['#d9534f', '#d9a441', '#2e9d75', '#8f7ac6']) assert.ok(bar.series[0].data.some((item) => item.color === color), '掌握状态调色板缺色 ' + color)
  const radar = options.radar
  assert.equal(radar.series[0]?.type, 'radar')
  assert.deepEqual(radar.radarIndicators.map((item) => item.max), [100, 100, 100, 100, 100])
  assert.ok(radar.radarIndicators.some((item) => item.name.includes('自评待验证')))
  assert.ok(radar.radarIndicators.some((item) => item.name.includes('未测量')))
  assert.deepEqual(radar.radarAxisName, [{ color: '#657b94', fontSize: 11 }], '雷达图文字颜色与字号保持')
  assert.equal(radar.series[0]?.lineColor, '#2058a7')
  assert.equal(radar.series[0]?.itemColor, '#2058a7')
  assert.equal(radar.series[0]?.areaColor, 'rgba(48, 171, 148, .22)')
  assert.deepEqual([radar.series[0]?.symbol, radar.series[0]?.symbolSize], ['circle', 5])
  assert.equal(radar.series[0]?.data[0]?.name, '当前掌握度')
  assert.deepEqual(radar.series[0]?.data[0]?.value, [82, 69, 76, 64, 90])
  const curve = options.difficulty
  assert.deepEqual(curve.series.map((item) => item.name), ['学习者准备度', '资源难度', '资源可信度'])
  assert.deepEqual(curve.series.map((item) => item.lineColor), ['#2f78dc', '#e58b39', '#7a5cc7'])
  assert.equal(curve.yAxis[0]?.min, 0)
  assert.equal(curve.yAxis[0]?.max, 100)
  assert.deepEqual(curve.xAxis[0]?.labelStyle, { color: '#61758c', fontSize: 10, width: 86, overflow: 'truncate' }, '资源曲线轴文字样式保持')
  assert.ok(curve.series.every((item) => item.data.some((point) => point.value === null)), '曲线未测数据应保留 null 空点')
  assert.equal(curve.legend[0]?.type, 'scroll')
  assert.deepEqual(curve.legend[0]?.textStyle, { color: '#637990', fontSize: 11 }, '资源曲线图例文字颜色与字号保持')
  const graph = options.path.series[0]
  assert.equal(graph?.type, 'graph')
  assert.equal(graph?.roam, true, '路径图 roam 必须保持')
  assert.equal(graph?.symbol, 'roundRect')
  assert.deepEqual(graph?.symbolSize, [136, 54], '路径图节点框保持 136×54')
  assert.deepEqual(graph?.labelStyle, { show: true, color: '#fff', fontSize: 12, fontWeight: 700, width: 112, overflow: 'truncate' }, '路径图标签颜色与字号保持')
  assert.deepEqual(Object.fromEntries(graph.data.map((item) => [item.name, item.color])), {
    '基础知识回顾': '#548b88', '风险评估与分层决策': '#f0a33a', '证据检索与质量核验': '#e66557',
    '协同路径规划': '#4f8dcc', '高风险病例复盘': '#9aaabd',
  }, '路径图节点状态颜色保持')
  assert.ok(graph.links.every((item) => item.color === '#5f9bd3' && item.width === 2.5), '当前聚焦路径的连线颜色与宽度保持')
  assert.ok(graph.links.length >= 3)
}
async function waitFor(predicate, label, timeout = 7000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 40))
  }
  throw new Error('等待超时：' + label)
}

async function saveShot(page, filename, fullPage = false) {
  const target = path.join(evidenceDir, filename)
  await page.screenshot({ path: target, fullPage, animations: 'disabled' })
  summary.screenshots.push(path.relative(frontendDir, target).replaceAll('\\', '/'))
}
async function saveRadarDifficultyShot(page, filename) {
  await page.locator('.report-visual-grid').scrollIntoViewIfNeeded()
  const radarTop = await page.locator('.report-radar-slot').evaluate((element) => element.getBoundingClientRect().top)
  await page.locator('.content-area').evaluate((element, delta) => { element.scrollTop += delta }, radarTop - 70)
  await page.waitForTimeout(1300)
  const measured = await page.evaluate(() => ({
    viewportHeight: innerHeight,
    boxes: ['.report-radar-slot', '.report-fit-slot'].map((selector) => {
      const element = document.querySelector(selector), rect = element?.getBoundingClientRect()
      return { selector, x: rect?.x, y: rect?.y, width: rect?.width, height: rect?.height, bottom: rect?.bottom }
    }),
  }))
  for (const box of measured.boxes) assert.ok(box.y >= 60 && box.bottom <= measured.viewportHeight && box.width > 0 && box.height > 0, '中段截图应完整包含 ' + box.selector + '：' + JSON.stringify(box))
  summary.middleChartScreenshot = { filename, viewport: { width: 1393, height: measured.viewportHeight }, boxes: measured.boxes }
  await saveShot(page, filename)
}
async function measureLayout(page, name, width, height, strict) {
  const value = await page.evaluate(() => {
    function box(selector) {
      const target = document.querySelector(selector)
      if (!target) return null
      const element = target.matches('.el-select') ? target : target.closest('.el-select') || target
      const rect = element.getBoundingClientRect()
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom }
    }
    const controls = [box('[aria-label="学习画像"]'), box('[aria-label="报告时间窗口"]'), box('.report-refresh-button')]
    const elements = [...document.querySelectorAll('.report-selector-row .el-select, .report-selector-row .report-refresh-button, .topbar-actions > button')]
      .filter((element) => element.getClientRects().length)
      .map((element) => ({ label: element.innerText.trim().replace(/\s+/g, ' ') || element.className, rect: element.getBoundingClientRect() }))
    const overlaps = []
    for (let a = 0; a < elements.length; a += 1) for (let b = a + 1; b < elements.length; b += 1) {
      const w = Math.min(elements[a].rect.right, elements[b].rect.right) - Math.max(elements[a].rect.left, elements[b].rect.left)
      const h = Math.min(elements[a].rect.bottom, elements[b].rect.bottom) - Math.max(elements[a].rect.top, elements[b].rect.top)
      if (w > 1 && h > 1) overlaps.push({ a: elements[a].label, b: elements[b].label, width: w, height: h })
    }
    return {
      viewportWidth: innerWidth, viewportHeight: innerHeight,
      documentWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
      reportWidth: document.querySelector('.report-page')?.getBoundingClientRect().width || null,
      controls, overlaps,
      verticalScrollContainers: (() => {
        const result = []
        let element = document.querySelector('.next-round-panel')?.parentElement
        while (element) {
          const style = getComputedStyle(element)
          if (element.scrollHeight > element.clientHeight + 1 && /auto|scroll|overlay/.test(style.overflowY)) {
            result.push({ selector: element.className?.toString() || element.tagName.toLowerCase(), scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, scrollTop: element.scrollTop })
          }
          element = element.parentElement
        }
        return result
      })(),
      collapsed: document.querySelector('.app-shell')?.classList.contains('is-sidebar-collapsed') || false,
    }
  })
  assert.equal(value.viewportWidth, width)
  assert.equal(value.viewportHeight, height)
  if (strict) {
    assert.ok(value.documentWidth <= width, name + ' 水平溢出：' + value.documentWidth + ' > ' + width)
    assert.deepEqual(value.overlaps, [], name + ' 控件重叠')
    for (const [index, control] of value.controls.entries()) assert.ok(control && control.height >= 44, name + ' 主控件 ' + (index + 1) + ' 高度不足44px')
    if (width <= 860) {
      assert.ok(value.verticalScrollContainers.length > 0, name + ' 窄屏应提供自然垂直滚动容器')
      await page.locator('.next-round-panel').scrollIntoViewIfNeeded()
      const reachability = await page.locator('.next-round-panel').evaluate((element) => {
        const rect = element.getBoundingClientRect()
        const scrollContainers = []
        let parent = element.parentElement
        while (parent) {
          if (parent.scrollHeight > parent.clientHeight + 1 && /auto|scroll|overlay/.test(getComputedStyle(parent).overflowY)) scrollContainers.push({ selector: parent.className?.toString() || parent.tagName.toLowerCase(), scrollTop: parent.scrollTop })
          parent = parent.parentElement
        }
        return { visible: rect.bottom > 0 && rect.top < innerHeight && rect.width > 0, scrollContainers }
      })
      assert.ok(reachability.visible, name + ' 下一轮建议无法自然到达')
      assert.ok(reachability.scrollContainers.some((container) => container.scrollTop > 0), name + ' 到达下一轮建议时未发生自然滚动')
      value.reachability = reachability
    }
  }
  summary.layouts.push({ name, ...value })
  return value
}
async function decorationSignature(page) {
  return page.evaluate(() => {
    const selectors = { refreshIcon: '.report-refresh-button .el-icon', topbarIcon: '.topbar-action .el-icon', focusMarker: '.report-focus i' }
    const result = {}
    for (const [name, selector] of Object.entries(selectors)) {
      const element = document.querySelector(selector)
      if (!element) { result[name] = null; continue }
      const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
      result[name] = {
        width: Number(rect.width.toFixed(2)), height: Number(rect.height.toFixed(2)),
        fontSize: style.fontSize, color: style.color, background: style.backgroundColor,
        borderRadius: style.borderRadius, boxShadow: style.boxShadow,
      }
    }
    return result
  })
}
async function contrastValues(page) {
  return page.evaluate(() => {
    function rgba(value) {
      const items = value.match(/[\d.]+/g)?.map(Number) || []
      return items.length < 3 ? null : [items[0], items[1], items[2], items.length > 3 ? items[3] : 1]
    }
    function ratio(element) {
      let parent = element, bg = [255, 255, 255, 1]
      while (parent) {
        const color = rgba(getComputedStyle(parent).backgroundColor)
        if (color && color[3] > 0.02) { bg = color; break }
        parent = parent.parentElement
      }
      const fg = rgba(getComputedStyle(element).color) || [0, 0, 0, 1]
      const actual = fg.slice(0, 3).map((value, index) => value * fg[3] + bg[index] * (1 - fg[3]))
      const luminance = (values) => {
        const channels = values.map((value) => {
          const v = value / 255
          return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
        })
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
      }
      const a = luminance(actual), b = luminance(bg.slice(0, 3))
      return Number(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2))
    }
    const selected = document.querySelector('.el-select-dropdown__item.is-selected')
    const button = document.querySelector('.report-refresh-button')
    return {
      selected: selected ? { text: selected.innerText.trim(), ratio: ratio(selected), color: getComputedStyle(selected).color, background: getComputedStyle(selected).backgroundColor } : null,
      button: button ? { text: button.innerText.trim(), ratio: ratio(button), color: getComputedStyle(button).color, background: getComputedStyle(button).backgroundColor } : null,
    }
  })
}
async function checkLongText(page) {
  const entries = await page.evaluate(() => {
    const selectors = ['.report-focus strong', '.report-hero > .el-alert .el-alert__title', '.next-round-panel p', '.suggestion-list span']
    return selectors.flatMap((selector) => [...document.querySelectorAll(selector)].map((element) => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect()
      const clipped = rect.width > 0 && (
        element.scrollWidth > element.clientWidth + 2
        || element.scrollHeight > element.clientHeight + 2
        || style.textOverflow === 'ellipsis'
        || style.webkitLineClamp !== 'none'
        || style.whiteSpace === 'nowrap'
      )
      return { selector, text: element.innerText.trim(), width: rect.width, height: rect.height, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, textOverflow: style.textOverflow, whiteSpace: style.whiteSpace, clipped }
    })).filter((item) => item.text.length > 25)
  })
  assert.ok(entries.length >= 2, '长文本 fixture 未命中')
  assert.ok(entries.every((item) => !item.clipped), '长文案被截断：' + JSON.stringify(entries.filter((item) => item.clipped)))
  return entries
}
async function stableHistorySignature(page, label) {
  await page.mouse.move(0, 0)
  await page.waitForTimeout(450)
  const sample = () => page.evaluate((view) => {
    const shell = document.querySelector('.app-shell')
    const styles = (selector) => {
      const element = document.querySelector(selector)
      if (!element) return null
      const s = getComputedStyle(element)
      return { color: s.color, background: s.backgroundColor, border: s.borderColor, shadow: s.boxShadow, radius: s.borderRadius, fontSize: s.fontSize, fontWeight: s.fontWeight, height: Number(element.getBoundingClientRect().height.toFixed(2)) }
    }
    return {
      historySelectorMatches: shell?.matches('.app-shell:has(.history-page)') || false,
      reportSelectorMatches: shell?.matches('.app-shell:has(.report-page)') || false,
      shellClass: shell?.className || '',
      topbar: styles('.topbar'), title: styles('.topbar-copy h1'),
      subtitle: styles('.topbar-copy p'), action: styles('.topbar-action'), meta: styles('.topbar-meta'), view,
    }
  }, label)
  let previous = null, stable = 0, current = null
  const deadline = Date.now() + 5000
  while (Date.now() < deadline) {
    current = await sample()
    if (JSON.stringify(current) === JSON.stringify(previous)) stable += 1
    else stable = 0
    if (stable >= 2) return current
    previous = current
    await page.waitForTimeout(90)
  }
  throw new Error('历史页主题过渡未稳定：' + JSON.stringify(current))
}
async function focusCheck(page) {
  const profile = page.getByRole('combobox', { name: '学习画像' })
  const refresh = page.getByRole('button', { name: /更新报告|Refresh/ })
  await profile.focus()
  await page.keyboard.press('Tab')
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), '报告时间窗口')
  await page.keyboard.press('Tab')
  const value = await page.evaluate(() => ({
    text: document.activeElement?.innerText?.trim() || '',
    focusVisible: document.activeElement?.matches(':focus-visible') || false,
    outline: getComputedStyle(document.activeElement).outlineStyle,
    shadow: getComputedStyle(document.activeElement).boxShadow,
  }))
  assert.ok(await refresh.count())
  assert.match(value.text, /更新报告|Refresh/)
  assert.equal(value.focusVisible, true, 'Tab 到主按钮后必须显示焦点')
  assert.ok(value.outline !== 'none' || value.shadow !== 'none', '键盘焦点没有可视样式')
  return value
}
async function reducedMotionCheck(page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const value = await page.evaluate(() => {
    const selectors = ['.report-hero', '.profile-selector', '.report-refresh-button', '.report-mastery-section', '.report-chart-slot', '.next-round-panel']
    const styles = selectors.flatMap((selector) => [...document.querySelectorAll(selector)].slice(0, 3).map((element) => {
      const s = getComputedStyle(element)
      return { selector, transition: s.transitionDuration.split(',').map((v) => parseFloat(v) || 0), animation: s.animationDuration.split(',').map((v) => parseFloat(v) || 0) }
    }))
    return { preference: matchMedia('(prefers-reduced-motion: reduce)').matches, styles }
  })
  assert.equal(value.preference, true)
  assert.ok(value.styles.every((item) => item.transition.every((n) => n === 0) && item.animation.every((n) => n === 0)), 'reduced-motion 未清除动效')
  return value
}
async function contractCheck(page) {
  assert.equal(await page.getByRole('heading', { name: '学习报告', level: 2 }).count(), 1)
  for (const selector of ['.report-hero', '.report-focus', '.profile-selector', '.report-summary-metrics', '.report-mastery-section', '.next-round-panel']) {
    assert.equal(await page.locator(selector).count(), 1, 'DOM contract missing: ' + selector)
  }
  assert.ok(await page.locator('.report-chart-slot').count() >= 1)
  const wrapped = await page.evaluate(() => {
    const content = [...document.querySelectorAll('.report-chart-slot')].map((slot) => slot.innerText).join('\n')
    return ['能力雷达图', '资源难度匹配曲线', '学习路径规划图'].every((name) => content.includes(name))
  })
  assert.ok(wrapped, '.report-chart-slot 必须包含雷达/曲线/路径图')
  assert.equal(await page.getByRole('combobox', { name: '学习画像' }).count(), 1, '画像控件缺 aria-label')
  assert.equal(await page.getByRole('combobox', { name: '报告时间窗口' }).count(), 1)
  assert.equal(await page.getByRole('button', { name: /更新报告|Refresh/ }).count(), 1)
}
async function waitForAudit(predicate, label, timeout = 7000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 40))
  }
  throw new Error('等待 API audit 超时：' + label)
}

async function screenshotSummary() {
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2), 'utf8')
}

try {
    fixtureMode = 'full'
    const page = await openReport({ width: 1393, height: 871 })
    await contractCheck(page)
    await page.getByText('初始校准：问卷预判第 3 阶，最终第 2 阶（已降阶校准）', { exact: false }).waitFor()
    for (const value of ['16', '23', '74%', '4']) await page.getByText(value, { exact: true }).waitFor()
    for (const text of ['巩固风险分层的核心判定条件', longSuggestion, '完成一轮循证核验与结构化交接练习']) await page.getByText(text, { exact: true }).waitFor()
    const initialOptions = await readChartOptions(page)
    validateChartOptions(initialOptions)
    summary.chartOptions = initialOptions
    summary.pathGraphLayout = await readPathGraphLayout(page)
    assertPathGraphVisible(summary.pathGraphLayout, 'desktop 1393×871')
    summary.checks.push({ name: 'path-node-frames-and-labels-visible-desktop', status: 'PASS', value: summary.pathGraphLayout })
    summary.decoration = await decorationSignature(page)
    for (const [name, expected] of Object.entries({
      refreshIcon: { width: 14, height: 14, fontSize: '14px', color: 'rgb(255, 255, 255)' },
      topbarIcon: { width: 14, height: 14, fontSize: '14px', color: 'rgb(23, 68, 126)' },
      focusMarker: { width: 7, height: 7, background: 'rgb(67, 143, 240)', borderRadius: '50%' },
    })) {
      assert.ok(summary.decoration[name], '缺少 ' + name)
      for (const [key, value] of Object.entries(expected)) assert.equal(summary.decoration[name][key], value, name + ' ' + key + ' 与 UI 合同不符')
    }
    summary.checks.push({ name: 'report-template-and-original-content-contract', status: 'PASS' })
    summary.checks.push({ name: 'four-real-echarts-series-scale-null-zoom-roam', status: 'PASS', charts: Object.keys(initialOptions) })
    summary.checks.push({ name: 'icons-marker-preserve-prechange-measurements', status: 'PASS', value: summary.decoration })

    await page.locator('.content-area').evaluate((element) => { element.scrollTop = 0 })
    await saveShot(page, 'report-desktop-1393x871.png')
    await saveRadarDifficultyShot(page, 'report-desktop-mid-radar-difficulty-1393x871.png')
    await page.locator('.report-chart-slot').last().scrollIntoViewIfNeeded()
    await page.waitForTimeout(1300)
    await saveShot(page, 'report-desktop-lower-1393x871.png')

    await page.getByRole('combobox', { name: '学习画像' }).press('ArrowDown')
    await page.getByRole('option', { name: /初始校准画像/ }).waitFor()
    const contrast = await contrastValues(page)
    assert.ok(contrast.selected?.ratio >= 4.5, '选中画像文字对比度不足：' + JSON.stringify(contrast.selected))
    assert.ok(contrast.button?.ratio >= 4.5, '刷新按钮文字对比度不足：' + JSON.stringify(contrast.button))
    summary.contrast = { selected: contrast.selected, button: contrast.button, minimumRatio: Math.min(contrast.selected.ratio, contrast.button.ratio) }
    await page.keyboard.press('Escape')
    summary.longText = await checkLongText(page)
    summary.checks.push({ name: 'long-report-text-untruncated', status: 'PASS', samples: summary.longText })
    summary.checks.push({ name: 'selection-and-primary-contrast-minimum-4-5', status: 'PASS', value: summary.contrast })

    summary.keyboard = await focusCheck(page)
    summary.checks.push({ name: 'tab-focus-visible-on-controls', status: 'PASS', value: summary.keyboard })

    const profile = page.getByRole('combobox', { name: '学习画像' })
    await profile.press('ArrowDown')
    await page.getByRole('option', { name: /初始校准画像/ }).click()
    await page.getByText('初始能力诊断尚未完成。完成问卷和客观测评后', { exact: false }).waitFor()
    for (const text of ['完成诊断后展示能力雷达图', '当前方向还没有可展示的学习节点', '暂无已发布且可关联能力节点的资源', '完成方向选择后展示学习路径']) await page.getByText(text, { exact: false }).waitFor()
    assert.equal(await page.locator('.report-mastery-section canvas').count(), 0, '未测诊断不得绘制掌握图')
    await saveShot(page, 'report-empty-calibration-1393x871.png')
    summary.checks.push({ name: 'calibration-pending-and-empty-charts', status: 'PASS' })

    await profile.press('ArrowDown')
    const mainProfileStart = audit.requests.length
    await page.getByRole('option', { name: /主学习画像/ }).click()
    await page.getByText('初始校准：问卷预判第 3 阶', { exact: false }).waitFor()
    await waitForAudit(() => audit.requests.slice(mainProfileStart).some((item) => item.path === '/api/report/learner-main' && item.query.includes('window_days=30') && item.responseStatus === 200), '主画像 report payload')
    await waitForAudit(() => audit.requests.slice(mainProfileStart).some((item) => item.path === '/api/report/learner-main/events' && item.query.includes('window_days=30') && item.query.includes('after_revision=rpt-learner-main-30-v1')), '主画像 report stream snapshot')
    for (const days of [7, 30, 90]) {
      const control = page.getByRole('combobox', { name: '报告时间窗口' })
      const windowStart = audit.requests.length
      await control.press('ArrowDown')
      await page.getByRole('option', { name: '近 ' + days + ' 天', exact: true }).click()
      await waitForAudit(() => audit.requests.slice(windowStart).some((item) => item.path === '/api/report/learner-main' && item.query.includes('window_days=' + days) && item.responseStatus === 200), 'window_days=' + days + ' report payload')
      await waitForAudit(() => audit.requests.slice(windowStart).some((item) => item.path === '/api/report/learner-main/events' && item.query.includes('window_days=' + days) && item.query.includes('after_revision=rpt-learner-main-' + days + '-v1')), 'window_days=' + days + ' report stream snapshot')
    }
    summary.checks.push({ name: 'profile-selection-and-7-30-90-window-get', status: 'PASS' })

    const beforeConditional = audit.requests.length
    await page.evaluate(() => window.dispatchEvent(new Event('online')))
    await waitForAudit(() => audit.requests.slice(beforeConditional).some((item) => item.path === '/api/report/learner-main' && item.responseStatus === 304), 'If-None-Match 304')
    const conditional = audit.requests.slice(beforeConditional).find((item) => item.path === '/api/report/learner-main' && item.responseStatus === 304)
    assert.ok(conditional?.ifNoneMatch, '304 GET 应携带 If-None-Match')
    summary.checks.push({ name: 'etag-304-response', status: 'PASS', request: conditional })

    const refresh = page.getByRole('button', { name: /更新报告|Refresh/ })
    const beforeMetric = await page.locator('.report-summary-metrics strong').first().innerText()
    forceNextUpdate = true
    const beforeForce = audit.requests.length
    await refresh.click()
    await waitForAudit(() => audit.requests.slice(beforeForce).some((item) => item.path === '/api/report/learner-main' && item.responseStatus === 200 && !item.ifNoneMatch), 'forced report GET')
    await waitFor(async () => (await page.locator('.report-summary-metrics strong').first().innerText()) !== beforeMetric, 'forced report metric')
    const forced = audit.requests.slice(beforeForce).find((item) => item.path === '/api/report/learner-main' && item.responseStatus === 200 && !item.ifNoneMatch)
    assert.ok(forced, '强制刷新需要清空 If-None-Match')
    summary.checks.push({ name: 'force-refresh-clears-etag-and-updates', status: 'PASS', request: forced })

    const oldCount = Number(await page.locator('.report-summary-metrics strong').first().innerText())
    const eventStart = audit.requests.length
    const expectedCount = emitChanged('learner-main', 90)
    await waitFor(async () => Number(await page.locator('.report-summary-metrics strong').first().innerText()) === expectedCount, 'report_changed forced refresh')
    const changedRefresh = audit.requests.slice(eventStart).find((item) => item.path === '/api/report/learner-main' && item.responseStatus === 200)
    assert.ok(changedRefresh && !changedRefresh.ifNoneMatch, 'SSE report_changed 必须强制无 ETag GET')
    assert.ok(expectedCount > oldCount)
    assert.ok(audit.requests.some((item) => item.path === '/api/report/learner-main/events' && item.query.includes('window_days=90')))
    summary.checks.push({ name: 'sse-report-changed-refreshes-payload', status: 'PASS', newCount: expectedCount, request: changedRefresh })

    await page.evaluate(() => window.dispatchEvent(new Event('offline')))
    await page.getByText('当前离线', { exact: true }).waitFor()
    summary.checks.push({ name: 'offline-status-label', status: 'PASS' })
    await page.evaluate(() => window.dispatchEvent(new Event('online')))
    await waitForAudit(() => audit.requests.some((item) => item.path === '/api/report/learner-main' && item.responseStatus === 304), 'online resumes conditional report GET')
    await measureLayout(page, 'desktop-expanded-1393x871', 1393, 871, true)
    await page.close()

    const collapsed = await openReport({ width: 1331, height: 871, collapsed: true })
    assert.equal(await collapsed.locator('.app-shell').evaluate((element) => element.classList.contains('is-sidebar-collapsed')), true)
    await measureLayout(collapsed, 'desktop-collapsed-1331x871', 1331, 871, true)
    await saveShot(collapsed, 'report-desktop-collapsed-1331x871.png')
    validateChartOptions(await readChartOptions(collapsed))
    await collapsed.close()

    const wide = await openReport({ width: 1920, height: 1080 })
    await measureLayout(wide, 'wide-1920x1080', 1920, 1080, true)
    await saveShot(wide, 'report-wide-1920x1080.png')
    validateChartOptions(await readChartOptions(wide))
    await wide.close()

    for (const [width, height] of [[390, 844], [375, 667]]) {
      const mobile = await openReport({ width, height, collapsed: true, reducedMotion: width === 390 })
      await saveShot(mobile, 'report-mobile-' + width + 'x' + height + '.png')
      await measureLayout(mobile, 'mobile-' + width + 'x' + height, width, height, true)
      await mobile.locator('.content-area').evaluate((element) => { element.scrollTop = 0 })
      await mobile.waitForTimeout(1300)
      validateChartOptions(await readChartOptions(mobile))
      if (width === 375) {
        const mobilePathLayout = await readPathGraphLayout(mobile)
        assertPathGraphVisible(mobilePathLayout, '375px mobile')
        summary.checks.push({ name: 'path-node-frames-and-labels-visible-375px', status: 'PASS', value: mobilePathLayout })
      }
      if (width === 390) {
        summary.reducedMotion = await reducedMotionCheck(mobile)
        await saveShot(mobile, 'report-mobile-reduced-motion-390x844.png')
      }
      await mobile.close()
    }
    const short = await openReport({ width: 1393, height: 620 })
    await measureLayout(short, 'short-window-1393x620', 1393, 620, true)
    await saveShot(short, 'report-short-window-1393x620.png')
    await short.close()

    fixtureMode = 'empty-profiles'
    const emptyProfiles = await newPage({ width: 1393, height: 871 })
    await emptyProfiles.goto(baseUrl + '/report', { waitUntil: 'domcontentloaded' })
    await emptyProfiles.getByRole('heading', { name: '学习报告', level: 2 }).waitFor()
    await emptyProfiles.locator('.report-refresh-button').waitFor()
    assert.equal(await emptyProfiles.getByRole('button', { name: /更新报告|Refresh/ }).isDisabled(), true, '空画像列表下刷新必须禁用')
    summary.disabledRefreshIcon = await emptyProfiles.locator('.report-refresh-button .el-icon').evaluate((element) => {
      const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
      return { width: Number(rect.width.toFixed(2)), height: Number(rect.height.toFixed(2)), fontSize: style.fontSize, color: style.color }
    })
    assert.deepEqual(summary.disabledRefreshIcon, { width: 14, height: 14, fontSize: '14px', color: 'rgb(140, 161, 174)' }, '禁用刷新图标保持原尺寸并使用 #8ca1ae')
    await saveShot(emptyProfiles, 'report-empty-profiles-1393x871.png')
    summary.checks.push({ name: 'empty-profile-list-disables-refresh', status: 'PASS', icon: summary.disabledRefreshIcon })
    await emptyProfiles.close()
    fixtureMode = 'full'

    const routed = await newPage({ width: 1393, height: 871, collapsed: true })
    await routed.goto(baseUrl + '/report', { waitUntil: 'domcontentloaded' })
    await routed.getByRole('heading', { name: '学习报告', level: 2 }).waitFor()
    await routed.getByRole('button', { name: '学习历史' }).click()
    await routed.locator('.history-page').waitFor()
    await routed.getByRole('heading', { name: '学习历史', level: 1 }).waitFor()
    const routedSig = await stableHistorySignature(routed, 'report-to-history')
    assert.equal(routedSig.reportSelectorMatches, false, '离开报告后 :has(.report-page) 应失配')
    assert.equal(routedSig.historySelectorMatches, true)

    const direct = await newPage({ width: 1393, height: 871, collapsed: true })
    await direct.goto(baseUrl + '/learning/history', { waitUntil: 'domcontentloaded' })
    await direct.locator('.history-page').waitFor()
    const directSig = await stableHistorySignature(direct, 'direct-history')
    assert.equal(directSig.reportSelectorMatches, false)
    const routedComparable = { ...routedSig }; delete routedComparable.view
    const directComparable = { ...directSig }; delete directComparable.view
    assert.deepEqual(routedComparable, directComparable, '从报告跳到历史页的顶栏样式应与直达结果一致')
    await saveShot(routed, 'report-to-history-style-isolation.png')
    summary.checks.push({ name: 'report-style-scope-clears-after-history-navigation', status: 'PASS', routed: routedSig, direct: directSig })
    await routed.close()
    await direct.close()

    assert.deepEqual(audit.unexpectedApi, [], '意外 API: ' + JSON.stringify(audit.unexpectedApi))
    assert.deepEqual(audit.externalRequests, [], '外部请求: ' + JSON.stringify(audit.externalRequests))
    assert.deepEqual(audit.writes, [], '本验收不应发送 API 写请求: ' + JSON.stringify(audit.writes))
    assert.deepEqual(audit.pageErrors, [], '页面错误: ' + JSON.stringify(audit.pageErrors))
    summary.checks.push({ name: 'api-external-write-pageerror-audit', status: 'PASS', apiCount: audit.requests.length, writes: audit.writes.length, unexpectedApi: 0, externalRequests: 0, pageErrors: 0 })
    summary.status = 'PASS'
} catch (error) {
  summary.status = 'FAIL'
  summary.failure = { message: error?.message || String(error), stack: error?.stack || null }
  throw error
} finally {
  for (const page of pages) if (!page.isClosed()) await page.close().catch(() => {})
  await context.close().catch(() => {})
  await browser.close().catch(() => {})
  await new Promise((resolve) => server.close(resolve))
  if (summary.status === 'PASS' || summary.status === 'FAIL') writeFileSync(summaryPath, JSON.stringify(summary, null, 2), 'utf8')
}
