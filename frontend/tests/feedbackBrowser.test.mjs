import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'feedback-ui')
if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before feedback browser verification')
}
mkdirSync(evidenceDir, { recursive: true })

const audit = { requests: [], writes: [], unexpectedApi: [], externalRequests: [], pageErrors: [] }
const summary = { status: 'RUNNING', evidence_type: 'browser_fixture', screenshots: [], screenshotScrollPositions: [], layout: [], checks: [], audit }
const resultIdentity = { attemptId: 'attempt-feedback-fixture-1', learnerId: 'learner-feedback-1' }
const questions = [
  {
    question_id: 'q-single', question_type: 'single_choice',
    question: '检索增强生成的检索阶段主要做什么？',
    options: ['从来源中检索相关片段', '直接生成未经核验的结论'],
    skill_node_id: 'node-retrieval', knowledge_point: '证据检索', difficulty: '初级', source: 'resource',
  },
  {
    question_id: 'q-multiple', question_type: 'multiple_choice',
    question: '哪些做法能让回答有据可查？',
    options: ['保留来源片段', '核对回答与来源', '忽略检索结果'],
    skill_node_id: 'node-grounding', knowledge_point: '证据核验', difficulty: '中级', source: 'resource',
  },
  {
    question_id: 'q-short', question_type: 'short_answer',
    question: '简要说明如何处理检索证据不足的情况。', options: [],
    skill_node_id: 'node-grounding', knowledge_point: '证据边界', difficulty: '中级', source: 'resource',
  },
]

function fixtureProfile() {
  return {
    learner_id: 'learner-feedback-1', learner_type: '个人学习者', knowledge_base_id: 'kb-feedback',
    skill_level: 'intermediate', profile_version: 1, learning_goal: '理解检索与证据核验',
    created_at: '2026-10-01T08:00:00Z',
  }
}

function fixtureResource() {
  return {
    resource_id: 'resource-feedback-1', learner_id: 'learner-feedback-1', run_id: 'run-feedback-1',
    batch_id: 'batch-feedback-1', resource_type: '讲义', resource_kind: 'learning_document',
    topic: 'RAG 检索与证据核验', title: 'RAG 检索与证据核验讲义', difficulty: '中级', version: 1,
    created_at: '2026-10-01T08:06:00Z', publication_status: 'published',
  }
}

function candidate(id, name, group, rank) {
  return {
    skill_node_id: id, name, priority_group: group, rank, reason_codes: ['NEXT_LEARNING_STEP'],
    mastery_score: 0.42, confidence: 'medium', prerequisite_ids: [], blocked_by_node_ids: [],
    tier: 1, tier_label: '基础阶段', eligibility_status: 'available',
  }
}

function feedbackResult(payload, confirmed = false) {
  const attemptId = resultIdentity.attemptId
  const learnerId = resultIdentity.learnerId
  const resourceId = 'resource-feedback-1'
  const now = payload?.submitted_at || '2026-10-09T02:00:00Z'
  const attempt = {
    schema_version: '1.0', attempt_id: attemptId, request_hash: 'a'.repeat(64), learner_id: learnerId,
    source_resource_id: resourceId, source_resource_version: 1, source_run_id: 'run-feedback-1', path_node_id: null,
    idempotency_key: payload?.idempotency_key || 'fixture-feedback-idempotency', expected_profile_version: 1,
    started_at: null, submitted_at: now, duration_ms: payload?.duration_ms || 0, hint_count: payload?.hint_count || 0,
    overall_score: 0.72,
    knowledge_point_results: [
      { knowledge_point_id: 'node-retrieval', question_ids: ['q-single'], correct_count: 1, total_count: 1, score: 1, duration_ms: 0, hint_count: 0 },
      { knowledge_point_id: 'node-grounding', question_ids: ['q-multiple', 'q-short'], correct_count: 1, total_count: 2, score: 0.5, duration_ms: 0, hint_count: 0 },
    ],
    metadata: payload?.metadata || { source: 'feedback_view', client_version: 'web', session_id: 'batch-feedback-1' },
    created_at: now,
  }
  const report = {
    total_score: 72, max_score: 100, score_rate: 0.72,
    question_results: questions.map((question, index) => ({
      question_id: question.question_id, question_type: question.question_type,
      correct: index === 0, score: index === 0 ? 30 : 21, max_score: index === 0 ? 30 : 35,
      knowledge_point: question.knowledge_point, skill_node_id: question.skill_node_id,
    })),
    next_step_recommendation: {
      title: '先巩固证据核验，再进入新的检索策略',
      description: '用一份短讲义复习检索结果与回答之间的证据对应关系。',
      learning_intent: 'learn_new_knowledge', default_learning_node_ids: ['node-new-retrieval'],
      default_new_node_ids: ['node-new-retrieval'], default_review_node_ids: ['node-grounding'],
      recommended_action: 'practice',
    },
    downgrade_learning_candidates: [],
    followup_selection: confirmed ? { selection_type: 'same_tier', node_names: ['检索策略'] } : {},
  }
  return {
    attempt,
    decision: {
      decision_id: 'decision-feedback-fixture-1', learner_id: learnerId, attempt_id: attemptId,
      action: 'practice', reason_codes: ['KNOWLEDGE_NEEDS_REINFORCEMENT'],
      decision_reason: '本轮测评显示，证据检索已有基础，证据核验仍可进一步巩固。',
      target_knowledge_point_ids: ['node-grounding'], recommended_tier: 1, remediation_return_tier: null,
      tier_transition: null, decision_hash: 'b'.repeat(64), created_at: now,
    },
    profile_version: 2, knowledge_state_updates: [{
      knowledge_point_id: 'node-grounding', before: null,
      after: { mastery: 0.42, status: 'weak', self_report_prior: null, confidence: 'medium', objective_evidence_count: 1,
        distinct_objective_source_count: 1, attempt_count: 1, last_evidence_type: 'learning_attempt',
        last_evidence_id: attemptId, last_attempt_id: attemptId, row_version: 1 },
      source_attempt_id: attemptId, reason: '基于本轮练习记录。',
    }],
    learning_path: { path_id: 'path-feedback-fixture-1', learner_id: learnerId, version: 2, status: 'active', nodes: [], created_at: now, updated_at: now },
    path_mutation: {
      mutation_id: 'mutation-feedback-fixture-1', learner_id: learnerId, path_id: 'path-feedback-fixture-1',
      attempt_id: attemptId, decision_id: 'decision-feedback-fixture-1', mutation_type: 'INSERT_PRACTICE',
      target_node_id: 'node-grounding', inserted_node_ids: [], unlocked_node_ids: [], completed_node_ids: [],
      reason_codes: ['KNOWLEDGE_NEEDS_REINFORCEMENT'], path_version_before: 1, path_version_after: 2, created_at: now,
    },
    feedback_status: 'applied', followup_generation_status: confirmed ? 'queued' : 'not_requested',
    followup_run_id: confirmed ? 'run-feedback-followup-1' : null,
    followup_run_ids: confirmed ? ['run-feedback-followup-1'] : [],
    followup_relations: [], followup_job_id: confirmed ? 'job-feedback-followup-1' : null,
    followup_error_code: null,
    analysis: {
      summary: '你能识别检索步骤，继续练习证据与回答的对应关系会更稳固。',
      reflection_insight: '你提到希望多练习核对步骤，下一轮会围绕这个目标安排内容。',
      profile_update_suggestions: [], learner_suggestions: ['提交回答前逐项核对来源。'],
      report_highlights: ['已完成三道测评题。'], analysis_status: 'fallback',
    },
    resource_options: [{ option_id: 'resource-option-1', title: '证据核验强化', description: '围绕本次待加强节点继续学习。',
      resource_types: ['讲义', '复习清单'], difficulty: '中级', target_knowledge_point_ids: ['node-grounding'] }],
    correction_package_option: {
      option_id: 'personalized-correction-package-v1', resource_type: '个性化纠错训练包', title: '薄弱点强化包',
      eligible: true, disabled_reason_code: null,
      selectable_targets: [{ skill_node_id: 'node-grounding', name: '证据核验', tier: 1 }],
      recommended_target_ids: ['node-grounding'], min_targets: 1, max_targets: 2,
      recommended_difficulty: '中级', snapshot_hash: 'c'.repeat(64),
    },
    generation_options: {
      schema_version: '1.0', learner_id: learnerId, knowledge_base_id: 'kb-feedback', profile_version: 2,
      snapshot_hash: 'd'.repeat(64), reinforce_weakness: [candidate('node-grounding', '证据核验', 'learned_not_mastered', 1)],
      learn_new_knowledge: [candidate('node-new-retrieval', '检索策略', 'unlearned', 1)],
      cross_tier_new_knowledge: [], cross_tier_prerequisite_review: [],
      learning_candidates: [candidate('node-new-retrieval', '检索策略', 'unlearned', 1)],
      recommended_node_ids: ['node-new-retrieval'], recommendation_type: 'current_tier',
    },
    feedback_report: report, idempotent_replay: false,
  }
}

function writeJson(res, value, status = 200) {
  res.statusCode = status
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(value))
}

let currentScenario = 'active'
const server = createServer(async (req, res) => {
  const url = new URL(req.url || '/', 'http://127.0.0.1')
  const method = (req.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    let rawBody = ''
    for await (const chunk of req) rawBody += chunk
    let body = null
    if (rawBody) {
      try { body = JSON.parse(rawBody) } catch { body = rawBody }
    }
    audit.requests.push({ method, path: url.pathname, query: url.search, body })
    const learnerId = 'learner-feedback-1'
    if (method === 'GET' && url.pathname === '/api/auth/me') {
      return writeJson(res, { user: { user_id: 'feedback-fixture-user', username: 'feedback.fixture', display_name: '反馈验收用户' } })
    }
    if (method === 'GET' && url.pathname === '/api/profiles/') {
      return writeJson(res, { items: [fixtureProfile()], total: 1 })
    }
    if (method === 'GET' && url.pathname === '/api/knowledge/domains') {
      return writeJson(res, { domains: [{ domain_id: 'domain-feedback', tracks: [{ track_id: 'kb-feedback', name: 'RAG 工程' }] }] })
    }
    if (method === 'GET' && url.pathname === `/api/resources/${learnerId}`) {
      return writeJson(res, { resources: currentScenario === 'no-task' ? [] : [fixtureResource()] })
    }
    if (method === 'GET' && url.pathname === '/api/generate/jobs') {
      const items = currentScenario === 'no-task' ? [] : [{
        run_id: 'run-feedback-1', batch_id: 'batch-feedback-1', learner_id: learnerId,
        job_status: 'completed', status: 'completed', created_at: '2026-10-01T08:00:00Z',
        finished_at: '2026-10-01T08:06:00Z', request_payload: { resource_types: ['讲义'] },
      }]
      return writeJson(res, { items, total: items.length })
    }
    if (method === 'GET' && url.pathname === `/api/feedback/results/${learnerId}`) return writeJson(res, [])
    if (method === 'GET' && url.pathname === `/api/feedback/evaluation/batch/${learnerId}/batch-feedback-1`) {
      return writeJson(res, {
        learner_id: learnerId, batch_id: 'batch-feedback-1', topic: 'RAG 检索与证据核验',
        resource_ids: ['resource-feedback-1'], total: questions.length, questions,
      })
    }
    if (method === 'POST' && url.pathname === '/api/feedback/attempts/batch/submit') {
      audit.writes.push({ path: url.pathname, body })
      return writeJson(res, feedbackResult(body))
    }
    if (method === 'POST' && url.pathname === '/api/feedback/followups/select') {
      audit.writes.push({ path: url.pathname, body })
      return writeJson(res, feedbackResult(null, true))
    }
    // Follow-up navigation mounts GenerateView. Its initial read-only requests belong
    // to the explicitly tested destination route; keep them isolated in this fixture.
    const refererPath = (() => { try { return new URL(req.headers.referer || '').pathname } catch { return '' } })()
    if (method === 'GET' && refererPath === '/generate') {
      audit.requests.at(-1).destination_route_read = true
      if (url.pathname === `/api/resources/${learnerId}`) return writeJson(res, { resources: [] })
      if (url.pathname === '/api/generate/jobs') return writeJson(res, { items: [] })
      return writeJson(res, {})
    }
    audit.unexpectedApi.push({ method, path: url.pathname })
    if (method !== 'GET') audit.writes.push({ path: url.pathname, body, allowed: false })
    return writeJson(res, { detail: 'Unexpected fixture API request' }, 404)
  }

  const decodedPath = decodeURIComponent(url.pathname)
  const candidatePath = path.resolve(distDir, `.${decodedPath}`)
  const safePrefix = distDir.endsWith(path.sep) ? distDir : distDir + path.sep
  let filePath = candidatePath.startsWith(safePrefix) || candidatePath === path.join(distDir, 'index.html')
    ? candidatePath : path.join(distDir, 'index.html')
  if (!existsSync(filePath) || !readFileSync(filePath).length) filePath = path.join(distDir, 'index.html')
  const extension = path.extname(filePath).toLowerCase()
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.ico': 'image/x-icon' }
  res.setHeader('content-type', types[extension] || 'application/octet-stream')
  res.end(readFileSync(filePath))
})

let browser
let serverStarted = false
let baseUrl = ''

async function openFeedbackPage(viewport, { scenario = 'active', collapsed = false, reducedMotion = false } = {}) {
  currentScenario = scenario
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(8000)
  page.on('pageerror', error => audit.pageErrors.push({ message: error.message, url: page.url() }))
  page.on('request', request => {
    const requestUrl = request.url()
    if (/^https?:/.test(requestUrl) && new URL(requestUrl).origin !== new URL(baseUrl).origin) {
      audit.externalRequests.push(requestUrl)
    }
  })
  await page.addInitScript(({ sidebarCollapsed }) => {
    localStorage.clear()
    localStorage.setItem('app_sidebar_collapsed', String(sidebarCollapsed))
  }, { sidebarCollapsed: collapsed })
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`${baseUrl}/feedback`, { waitUntil: 'domcontentloaded' })
  await page.locator('.feedback-page').waitFor()
  await page.getByRole('button', { name: /开始测评|再次测评/ }).waitFor()
  await page.waitForFunction(() => document.querySelector('.feedback-page')?.getBoundingClientRect().width > 0)
  await assertTopbarVisible(page, `${viewport.width}x${viewport.height}-initial`)
  return page
}

async function screenshot(page, name, fullPage = true) {
  const target = path.join(evidenceDir, name)
  const scroll = await scrollPosition(page)
  await page.screenshot({ path: target, fullPage, animations: 'disabled' })
  summary.screenshots.push(path.relative(frontendDir, target).replaceAll('\\', '/'))
  summary.screenshotScrollPositions.push({ name, ...scroll })
}

async function scrollPosition(page) {
  return page.evaluate(() => {
    const main = document.querySelector('.main-area')
    const content = document.querySelector('.content-area')
    return {
      windowY: window.scrollY,
      documentElementY: document.documentElement.scrollTop,
      bodyY: document.body.scrollTop,
      mainAreaY: main?.scrollTop || 0,
      mainAreaX: main?.scrollLeft || 0,
      contentAreaY: content?.scrollTop || 0,
      contentAreaX: content?.scrollLeft || 0,
    }
  })
}

async function resetScrollPosition(page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
    const main = document.querySelector('.main-area')
    const content = document.querySelector('.content-area')
    if (main) { main.scrollTop = 0; main.scrollLeft = 0 }
    if (content) { content.scrollTop = 0; content.scrollLeft = 0 }
  })
  await page.waitForFunction(() => {
    const content = document.querySelector('.content-area')
    return window.scrollY === 0 && document.documentElement.scrollTop === 0 && (!content || content.scrollTop === 0)
  })
}

async function assertTopbarVisible(page, name) {
  const geometry = await page.evaluate(() => {
    const rect = element => {
      if (!element) return null
      const box = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return { x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom,
        visible: style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0 }
    }
    const topbar = document.querySelector('.topbar')
    const title = topbar?.querySelector('h1')
    const scrollAncestors = []
    for (let ancestor = title?.parentElement; ancestor && ancestor !== document.documentElement; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor)
      const rect = ancestor.getBoundingClientRect()
      const clips = ['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowX)
        || ['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowY)
      if (!clips) continue
      scrollAncestors.push({
        tag: ancestor.tagName.toLowerCase(),
        className: typeof ancestor.className === 'string' ? ancestor.className : '',
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        x: rect.x,
        y: rect.y,
        right: rect.right,
        bottom: rect.bottom,
        scrollTop: ancestor.scrollTop,
        scrollLeft: ancestor.scrollLeft,
        clientWidth: ancestor.clientWidth,
        scrollWidth: ancestor.scrollWidth,
        clientHeight: ancestor.clientHeight,
        scrollHeight: ancestor.scrollHeight,
      })
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      scroll: { windowY: window.scrollY, documentElementY: document.documentElement.scrollTop,
        bodyY: document.body.scrollTop, mainAreaY: document.querySelector('.main-area')?.scrollTop || 0,
        mainAreaX: document.querySelector('.main-area')?.scrollLeft || 0,
        contentAreaY: document.querySelector('.content-area')?.scrollTop || 0,
        contentAreaX: document.querySelector('.content-area')?.scrollLeft || 0 },
      scrollAncestors,
      topbar: rect(topbar), title: rect(title),
      actions: [...(topbar?.querySelectorAll('.topbar-action') || [])].map(element => ({ text: element.innerText.trim(), ...rect(element) })),
    }
  })
  assert.ok(geometry.topbar?.visible, `${name}: topbar is not visible: ${JSON.stringify(geometry)}`)
  assert.ok(geometry.title?.visible, `${name}: topbar title is not visible: ${JSON.stringify(geometry)}`)
  assert.ok(geometry.topbar.y >= -1 && geometry.topbar.bottom <= geometry.viewport.height + 1,
    `${name}: topbar is clipped by viewport: ${JSON.stringify(geometry)}`)
  assert.ok(geometry.title.y >= Math.max(geometry.topbar.y, 0) - 1 && geometry.title.bottom <= Math.min(geometry.topbar.bottom, geometry.viewport.height) + 1,
    `${name}: title escapes topbar/viewport: ${JSON.stringify(geometry)}`)
  for (const ancestor of geometry.scrollAncestors) {
    if (['hidden', 'clip', 'auto', 'scroll'].includes(ancestor.overflowX)) {
      assert.ok(geometry.title.x >= ancestor.x - 1 && geometry.title.right <= ancestor.right + 1,
        `${name}: title is clipped by horizontal overflow ancestor: ${JSON.stringify({ ancestor, title: geometry.title })}`)
    }
    if (['hidden', 'clip', 'auto', 'scroll'].includes(ancestor.overflowY)) {
      assert.ok(geometry.title.y >= ancestor.y - 1 && geometry.title.bottom <= ancestor.bottom + 1,
        `${name}: title is clipped by vertical overflow ancestor: ${JSON.stringify({ ancestor, title: geometry.title })}`)
    }
  }
  for (const action of geometry.actions) {
    assert.ok(action.visible, `${name}: topbar action is not visible: ${JSON.stringify(action)}`)
    assert.ok(action.x >= -1 && action.right <= geometry.viewport.width + 1 && action.y >= geometry.topbar.y - 1 && action.bottom <= Math.min(geometry.topbar.bottom, geometry.viewport.height) + 1,
      `${name}: topbar action is clipped: ${JSON.stringify(action)}`)
  }
  summary.checks.push({ name: `topbar-visible-${name}`, geometry })
  return geometry
}

async function layoutSnapshot(page, name) {
  const data = await page.evaluate(() => {
    const feedback = document.querySelector('.feedback-page')
    const shell = document.querySelector('.app-shell')
    const content = document.querySelector('.content-area')
    const box = element => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, clientHeight: document.documentElement.clientHeight, scrollHeight: document.documentElement.scrollHeight },
      scroll: { windowY: window.scrollY, documentElementY: document.documentElement.scrollTop, bodyY: document.body.scrollTop,
        mainAreaY: document.querySelector('.main-area')?.scrollTop || 0,
        mainAreaX: document.querySelector('.main-area')?.scrollLeft || 0,
        contentAreaY: content.scrollTop || 0, contentAreaX: content.scrollLeft || 0 },
      shell: box(shell), content: box(content), feedback: box(feedback),
      topbar: box(document.querySelector('.topbar')),
      topbarTitle: box(document.querySelector('.topbar h1')),
      topbarActions: [...document.querySelectorAll('.topbar-action')].map(box),
      hero: box(feedback?.querySelector('.feedback-hero')),
      workspace: box(feedback?.querySelector('.feedback-workspace')),
      result: box(feedback?.querySelector('.result-panel')),
    }
  })
  assert.ok(data.document.scrollWidth <= data.document.clientWidth + 1, `${name}: horizontal page overflow ${data.document.scrollWidth}/${data.document.clientWidth}`)
  summary.layout.push({ name, ...data })
  return data
}

async function assertTouchTargets(page, name) {
  const result = await page.evaluate(() => {
    const selectors = [
      '.start-evaluation-button', '.submit-feedback-button', '.custom-generation-button',
      '.correction-package-card > .el-button', '.selected-followup-card > .el-button',
      '.question-card .answer-options .el-radio', '.question-card .answer-options .el-checkbox',
    ]
    return selectors.flatMap(selector => [...document.querySelectorAll(selector)]).filter(element => {
      const style = getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
    }).map(element => {
      const rect = element.getBoundingClientRect()
      return { selector: element.className?.toString() || element.tagName, text: element.innerText?.trim().slice(0, 60), x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom }
    })
  })
  const short = result.filter(target => target.height < 44)
  assert.deepEqual(short, [], `${name}: touch targets shorter than 44px: ${JSON.stringify(short)}`)
  const viewportWidth = await page.evaluate(() => innerWidth)
  const outside = result.filter(target => target.x < -1 || target.right > viewportWidth + 1)
  assert.deepEqual(outside, [], `${name}: touch target clipped horizontally: ${JSON.stringify(outside)}`)
  await assertNoTargetOverlap(page, '.feedback-page button', `${name} buttons`)
  summary.checks.push({ name, touchTargets: result })
}

async function assertNoTargetOverlap(page, selector, name) {
  const overlaps = await page.locator(selector).evaluateAll(elements => {
    const visible = elements.map(element => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return { element, rect, visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0 }
    }).filter(item => item.visible)
    const result = []
    for (let left = 0; left < visible.length; left += 1) {
      for (let right = left + 1; right < visible.length; right += 1) {
        const a = visible[left].rect; const b = visible[right].rect
        const width = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (width > 1 && height > 1) result.push({ a: visible[left].element.innerText?.trim(), b: visible[right].element.innerText?.trim(), width, height })
      }
    }
    return result
  })
  assert.deepEqual(overlaps, [], `${name}: overlapping controls: ${JSON.stringify(overlaps)}`)
}

async function contrastRatio(element) {
  return element.evaluate(node => {
    const rgb = value => {
      const match = String(value).match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)/i)
      if (!match) return null
      return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])]
    }
    const blend = (foreground, background) => foreground.slice(0, 3).map((channel, index) => channel * foreground[3] + background[index] * (1 - foreground[3]))
    const luminance = color => {
      const channels = color.map(channel => channel / 255).map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const foreground = rgb(getComputedStyle(node).color)
    if (!foreground || foreground[3] < 0.98) return { ratio: 0, color: getComputedStyle(node).color, background: 'unresolved foreground' }
    let background = [255, 255, 255]
    const layers = []
    for (let current = node; current && current !== document.documentElement; current = current.parentElement) {
      const style = getComputedStyle(current)
      const layer = rgb(style.backgroundColor)
      if (layer && layer[3] > 0) layers.push({ color: layer, css: style.backgroundColor })
    }
    for (const layer of layers.reverse()) background = blend(layer.color, background)
    const foregroundLuminance = luminance(foreground.slice(0, 3))
    const backgroundLuminance = luminance(background)
    const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
    return { ratio, color: getComputedStyle(node).color, composedBackground: background, layers }
  })
}

async function assertReadableSelection(page) {
  const selections = page.locator('.answer-options .el-radio.is-checked .el-radio__label, .answer-options .el-checkbox.is-checked .el-checkbox__label')
  const count = await selections.count()
  assert.ok(count > 0, 'no selected option to measure')
  const contrasts = []
  for (let index = 0; index < count; index += 1) {
    const contrast = await contrastRatio(selections.nth(index))
    assert.ok(contrast.ratio >= 4.5, `selected option contrast ${contrast.ratio.toFixed(2)}:1 (${JSON.stringify(contrast)})`)
    contrasts.push(contrast)
  }
  summary.checks.push({ name: 'selected-option-contrast', contrasts })
}

async function assertKeyboardFocus(page, selector) {
  await page.evaluate(() => document.activeElement?.blur())
  let matched = false
  for (let index = 0; index < 60; index += 1) {
    await page.keyboard.press('Tab')
    matched = await page.evaluate(target => document.activeElement?.matches(target) || false, selector)
    if (matched) break
  }
  assert.ok(matched, `keyboard tab order did not reach ${selector}`)
  const style = await page.locator(selector).evaluate(element => {
    const computed = getComputedStyle(element)
    return { focusVisible: element.matches(':focus-visible'), outlineStyle: computed.outlineStyle, outlineWidth: computed.outlineWidth, outlineColor: computed.outlineColor, boxShadow: computed.boxShadow }
  })
  assert.ok(style.focusVisible, `${selector} is not :focus-visible after keyboard navigation`)
  assert.ok(style.outlineStyle !== 'none' && style.outlineWidth !== '0px' || style.boxShadow !== 'none', `${selector} lacks a visible keyboard focus indicator: ${JSON.stringify(style)}`)
  summary.checks.push({ name: 'keyboard-focus', selector, style })
}

async function assertElementPlusFieldFocus(page, label, control, focusShell, {
  singleBorderControl = false,
  inspector = control,
  keyboardFocus = true,
  screenshotName = null,
} = {}) {
  const baseline = await focusShell.evaluate((shell) => {
    const style = getComputedStyle(shell)
    return { borderColor: style.borderTopColor, borderWidth: style.borderTopWidth, boxShadow: style.boxShadow, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth }
  })
  await control.click()
  const shellHandle = await focusShell.elementHandle()
  const controlHandle = await control.elementHandle()
  const inspectorHandle = await inspector.elementHandle()
  const readFocusedStyle = () => page.evaluate(({ shell, control, input }) => {
    const shellStyle = getComputedStyle(shell)
    const controlStyle = getComputedStyle(control)
    const inputStyle = getComputedStyle(input)
    return {
      activeControl: document.activeElement === control,
      activeInput: document.activeElement === input,
      focusWithin: shell.matches(':focus-within'),
      hovered: shell.matches(':hover'),
      shell: { borderColor: shellStyle.borderTopColor, borderWidth: shellStyle.borderTopWidth, boxShadow: shellStyle.boxShadow, outlineStyle: shellStyle.outlineStyle, outlineWidth: shellStyle.outlineWidth },
      control: { outlineStyle: controlStyle.outlineStyle, outlineWidth: controlStyle.outlineWidth },
      input: {
        outlineStyle: inputStyle.outlineStyle, outlineWidth: inputStyle.outlineWidth,
        borderWidths: ['Top', 'Right', 'Bottom', 'Left'].map((side) => Number.parseFloat(inputStyle['border' + side + 'Width']) || 0),
      },
    }
  }, { shell: shellHandle, control: controlHandle, input: inspectorHandle })
  const mouseFocusedImmediate = await readFocusedStyle()
  await page.waitForTimeout(240)
  const mouseFocused = await readFocusedStyle()
  if (screenshotName) await screenshot(page, screenshotName, false)
  summary.checks.push({ name: `element-plus-field-focus-${label}`, baseline, mouseFocusedImmediate, mouseFocused })
  const debug = JSON.stringify({ baseline, mouseFocusedImmediate, mouseFocused })
  assert.ok(mouseFocused.activeControl || mouseFocused.activeInput, `${label}: click should focus the visible field or its inner input: ${debug}`)
  assert.equal(mouseFocused.focusWithin, true, `${label}: outer Element Plus shell should retain focus-within: ${debug}`)
  assert.equal(mouseFocused.hovered, true, `${label}: focus sample must keep the pointer over the control: ${debug}`)
  for (const [who, style] of [['wrapper', mouseFocused.shell], ['visible control', mouseFocused.control], ['inner input', mouseFocused.input]]) {
    assert.ok(style.outlineStyle === 'none' || Number.parseFloat(style.outlineWidth) === 0,
      `${label}: ${who} should not draw a duplicate outline: ${debug}`)
  }
  if (!singleBorderControl) {
    assert.ok(mouseFocused.input.borderWidths.every((width) => width <= 0.5),
      `${label}: inner input should not draw a separate border: ${debug}`)
  }
  const shadowVisible = mouseFocused.shell.boxShadow !== 'none'
    && mouseFocused.shell.boxShadow !== baseline.boxShadow
    && !/rgba\([^)]*,\s*0(?:\.0+)?\)/i.test(mouseFocused.shell.boxShadow)
  const borderVisible = mouseFocused.shell.borderColor !== baseline.borderColor
    && Number.parseFloat(mouseFocused.shell.borderWidth) > 0
  assert.ok(shadowVisible || borderVisible,
    `${label}: the outer shell should show a clear focus border or shadow while hovered: ${debug}`)

  if (keyboardFocus) {
    await page.keyboard.press('Escape')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    const keyboardFocused = await page.evaluate(({ shell, control, input }) => ({
      activeControl: document.activeElement === control,
      activeInput: document.activeElement === input,
      focusVisible: document.activeElement?.matches(':focus-visible') || false,
      shellFocusWithin: shell.matches(':focus-within'),
    }), { shell: shellHandle, control: controlHandle, input: inspectorHandle })
    assert.ok(keyboardFocused.activeControl || keyboardFocused.activeInput, `${label}: Tab and Shift+Tab should return keyboard focus to the field: ${JSON.stringify(keyboardFocused)}`)
    assert.equal(keyboardFocused.focusVisible, true, `${label}: keyboard focus should use :focus-visible: ${JSON.stringify(keyboardFocused)}`)
    summary.checks.push({ name: `element-plus-field-keyboard-${label}`, keyboardFocused })
  }
}

async function chooseFilterableOptionWithKeyboard(page, select, searchText, expectedText, label) {
  const input = select.locator('input').first()
  await input.click()
  await input.fill(searchText)
  await input.press('ArrowDown')
  await input.press('Enter')
  await page.waitForTimeout(30)
  const selectedText = await select.innerText()
  assert.ok(selectedText.includes(expectedText), `${label}: keyboard option selection should choose ${expectedText}; got ${selectedText}`)
  summary.checks.push({ name: `filterable-select-keyboard-${label}`, selectedText })
}

async function checkReducedMotion(page) {
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true)
  await page.locator('.start-evaluation-button').click()
  await page.locator('.question-card').first().waitFor()
  await page.waitForTimeout(80)
  const running = await page.evaluate(() => [...document.getAnimations()].filter(animation => {
    const target = animation.effect?.target
    return animation.playState === 'running' && target && document.querySelector('.feedback-page')?.contains(target)
  }).map(animation => ({ target: animation.effect?.target?.className?.toString(), playState: animation.playState })))
  assert.deepEqual(running, [], `feedback page has running animations under reduced motion: ${JSON.stringify(running)}`)
  summary.checks.push({ name: 'reduced-motion', runningAnimations: running })
}

async function checkNoTaskAndPreStart() {
  const page = await openFeedbackPage({ width: 1393, height: 871 }, { scenario: 'no-task' })
  try {
    await page.getByText('暂时没有可用于反馈的资源任务', { exact: false }).waitFor()
    await assertFeedbackPreparationState(page, 'no-batch-preparation', { hasBatch: false })
    await resetScrollPosition(page)
    await assertTopbarVisible(page, 'no-batch-top')
    await screenshot(page, 'feedback-no-batch-1393x871.png')
    await layoutSnapshot(page, 'no-batch-desktop')
    summary.checks.push({ name: 'no-batch-state', startDisabled: true, questions: 0 })
  } finally { await page.close() }
}

async function assertFeedbackPreparationState(page, label, { hasBatch = true, screenshotName = null } = {}) {
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { x: value.x, y: value.y, right: value.right, bottom: value.bottom, width: value.width, height: value.height }
    }
    const workspace = document.querySelector('.feedback-workspace')
    const evaluation = document.querySelector('.evaluation-panel')
    const reflection = document.querySelector('.reflection-panel')
    const evaluationPreparation = document.querySelector('.evaluation-preparation')
    const reflectionPreparation = document.querySelector('.reflection-preparation')
    const start = document.querySelector('.start-evaluation-button')
    const startStyle = start ? getComputedStyle(start) : null
    const layoutRect = (node) => {
      const box = rect(node)
      return box ? { ...box, top: box.y } : null
    }
    const pseudoRule = (node, pseudo, box) => {
      if (!node || !box) return null
      const style = getComputedStyle(node, pseudo)
      const left = Number.parseFloat(style.left) || 0
      const right = Number.parseFloat(style.right) || 0
      const top = Number.parseFloat(style.top) || 0
      const width = Number.parseFloat(style.width) || Math.max(box.width - left - right, 0)
      const height = Number.parseFloat(style.height) || 0
      return {
        visible: style.content !== 'none' && style.display !== 'none' && style.visibility !== 'hidden'
          && style.position === 'absolute' && width > 0 && height > 0,
        left: box.x + left,
        right: box.x + box.width - right,
        top: box.y + top,
        width,
        height,
        color: style.backgroundColor,
      }
    }
    const preparationLayout = (panel) => {
      const footerNode = panel?.querySelector('.preparation-footer')
      const footer = layoutRect(footerNode)
      return {
        heading: layoutRect(panel?.querySelector('.preparation-heading')),
        steps: [...(panel?.querySelectorAll('.preparation-steps > li') || [])].map((node) => {
          const row = layoutRect(node)
          const number = node.querySelector('.preparation-number')
          const connectorStyle = getComputedStyle(node, '::after')
          const connectorWidth = Number.parseFloat(connectorStyle.width) || 0
          const connectorLeft = Number.parseFloat(connectorStyle.left) || 0
          const connectorTop = Number.parseFloat(connectorStyle.top) || 0
          const connectorBottom = Number.parseFloat(connectorStyle.bottom) || 0
          return {
            ...row,
            number: layoutRect(number),
            separator: pseudoRule(node, '::before', row),
            connector: {
              visible: connectorStyle.content !== 'none' && connectorStyle.display !== 'none'
                && connectorStyle.position === 'absolute' && connectorWidth > 0,
              left: row.x + connectorLeft,
              right: row.x + connectorLeft + connectorWidth,
              top: row.y + connectorTop,
              bottom: row.y + row.height - connectorBottom,
            },
          }
        }),
        footer,
        footerBorderTopWidth: footerNode ? Number.parseFloat(getComputedStyle(footerNode).borderTopWidth) || 0 : 0,
        footerSeparator: pseudoRule(footerNode, '::before', footer),
        headingCount: panel?.querySelectorAll('.preparation-heading').length || 0,
        stepsCount: panel?.querySelectorAll('.preparation-steps > li').length || 0,
        footerCount: panel?.querySelectorAll('.preparation-footer').length || 0,
      }
    }
    return {
      document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      viewport: { width: innerWidth, height: innerHeight },
      workspace: workspace && { ...rect(workspace), scrollWidth: workspace.scrollWidth, clientWidth: workspace.clientWidth },
      evaluationPanel: rect(evaluation), reflectionPanel: rect(reflection),
      evaluationPreparation: rect(evaluationPreparation), reflectionPreparation: rect(reflectionPreparation),
      preparationColumns: {
        evaluation: preparationLayout(evaluationPreparation),
        reflection: preparationLayout(reflectionPreparation),
      },
      duplicateBatchContextCount: workspace?.querySelectorAll('.preparation-batch-context, .evaluation-preparation .preparation-context').length || 0,
      duplicateBatchLabels: [...(workspace?.querySelectorAll('.preparation-batch-context dt, .evaluation-preparation .preparation-context dt') || [])]
        .map(node => node.innerText.trim()).filter(text => ['当前方向', '本轮材料'].includes(text)),
      preparationText: [evaluationPreparation?.innerText, reflectionPreparation?.innerText].filter(Boolean).join('\n'),
      questionCount: workspace?.querySelectorAll('.question-card').length || 0,
      reflectionFormCount: workspace?.querySelectorAll('.reflection-fields, .submit-box').length || 0,
      legacyEmptyCount: workspace?.querySelectorAll('.el-empty').length || 0,
      start: start && { ...rect(start), disabled: start.disabled, display: startStyle.display, visibility: startStyle.visibility },
    }
  })
  assert.ok(metrics.evaluationPreparation, `${label}: the evaluation preparation panel should be present: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.reflectionPreparation, `${label}: the short reflection preparation note should be present: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.preparationText.trim().length > 0, `${label}: preparation guidance should be readable`)
  assert.equal(metrics.questionCount, 0, `${label}: questions should stay collapsed until the user starts the evaluation`)
  assert.equal(metrics.reflectionFormCount, 0, `${label}: reflection inputs and submit area should stay collapsed before questions load`)
  assert.equal(metrics.legacyEmptyCount, 0, `${label}: the old Element Plus empty illustration should not remain in the preparation state`)
  assert.equal(metrics.duplicateBatchContextCount, 0, `${label}: the left preparation column should not repeat the profile/batch context: ${JSON.stringify(metrics.duplicateBatchLabels)}`)
  assert.deepEqual(metrics.duplicateBatchLabels, [], `${label}: duplicate current-direction/material labels should be removed`)
  assert.ok(metrics.start && metrics.start.height >= 44 && metrics.start.visibility !== 'hidden', `${label}: the original start action must remain reachable: ${JSON.stringify(metrics.start)}`)
  assert.ok(metrics.start.x >= -1 && metrics.start.right <= metrics.viewport.width + 1, `${label}: the start action must not be horizontally clipped: ${JSON.stringify(metrics.start)}`)
  assert.equal(metrics.start.disabled, !hasBatch, `${label}: start availability should follow the selected batch`)
  assert.ok(metrics.document.scrollWidth <= metrics.document.clientWidth + 1, `${label}: document horizontal overflow ${JSON.stringify(metrics.document)}`)
  if (metrics.workspace) assert.ok(metrics.workspace.scrollWidth <= metrics.workspace.clientWidth + 1, `${label}: feedback workspace horizontal overflow ${JSON.stringify(metrics.workspace)}`)
  if (metrics.viewport.width >= 1100) {
    assert.ok(metrics.evaluationPanel && metrics.reflectionPanel, `${label}: desktop preparation should keep both columns`)
    assert.ok(Math.abs(metrics.evaluationPanel.y - metrics.reflectionPanel.y) <= 1, `${label}: preparation columns should share their top edge: ${JSON.stringify(metrics)}`)
    assert.ok(Math.abs(metrics.evaluationPanel.bottom - metrics.reflectionPanel.bottom) <= 1, `${label}: preparation columns should share their bottom edge: ${JSON.stringify(metrics)}`)
    const left = metrics.preparationColumns.evaluation
    const right = metrics.preparationColumns.reflection
    assert.equal(left.headingCount, 1, `${label}: evaluation preparation should have one Shared PreparationPanel heading`)
    assert.equal(right.headingCount, 1, `${label}: reflection preparation should have one Shared PreparationPanel heading`)
    assert.equal(left.stepsCount, 3, `${label}: evaluation preparation should keep its three next-step points`)
    assert.equal(right.stepsCount, 3, `${label}: reflection preparation should keep its three next-step points`)
    assert.equal(left.footerCount, 1, `${label}: evaluation preparation should keep its footer`)
    assert.equal(right.footerCount, 1, `${label}: reflection preparation should keep its footer`)
    for (const column of [left, right]) {
      assert.equal(column.footerBorderTopWidth, 0, `${label}: footer separator should use its aligned pseudo rule, not a full-width border`)
      assert.ok(column.footerSeparator?.visible && Math.abs(column.footerSeparator.height - 1) <= 0.1,
        `${label}: footer should keep a visible 1px aligned separator: ${JSON.stringify(column.footerSeparator)}`)
      for (let index = 0; index < column.steps.length; index += 1) {
        const step = column.steps[index]
        assert.ok(step.number && step.separator.visible,
          `${label}: preparation point ${index + 1} should keep a measurable horizontal divider: ${JSON.stringify(step)}`)
        assert.ok(Math.abs(step.separator.height - 1) <= 0.1 && step.separator.color === column.footerSeparator.color,
          `${label}: step and footer rules should share the same 1px thickness and color: ${JSON.stringify({ step: step.separator, footer: column.footerSeparator })}`)
        assert.ok(Math.abs(step.separator.left - column.footerSeparator.left) <= 1,
          `${label}: step and footer rules should start at the same text-column x position: ${JSON.stringify({ step: step.separator, footer: column.footerSeparator })}`)
        assert.ok(step.separator.left > step.number.right + 1,
          `${label}: horizontal divider should start beyond the number column: ${JSON.stringify(step)}`)
        if (index < column.steps.length - 1) {
          assert.ok(step.connector.visible, `${label}: numbered steps should retain their vertical connector: ${JSON.stringify(step.connector)}`)
          assert.ok(step.connector.left >= step.number.x - 1 && step.connector.right <= step.number.right + 1,
            `${label}: vertical connector should stay in the number column: ${JSON.stringify(step)}`)
          const nextSeparator = column.steps[index + 1].separator
          const verticalOverlap = nextSeparator.top >= step.connector.top - 1 && nextSeparator.top <= step.connector.bottom + 1
          const horizontalOverlap = nextSeparator.left < step.connector.right && nextSeparator.right > step.connector.left
          assert.equal(verticalOverlap && horizontalOverlap, false,
            `${label}: text-column divider should not cross the previous number connector: ${JSON.stringify({ connector: step.connector, divider: nextSeparator })}`)
        }
      }
    }
    assert.ok(Math.abs(left.heading.top - right.heading.top) <= 1 && Math.abs(left.heading.bottom - right.heading.bottom) <= 1,
      `${label}: preparation headings should align across columns: ${JSON.stringify(metrics.preparationColumns)}`)
    for (let index = 0; index < 3; index += 1) {
      assert.ok(Math.abs(left.steps[index].top - right.steps[index].top) <= 1 && Math.abs(left.steps[index].bottom - right.steps[index].bottom) <= 1,
        `${label}: preparation point ${index + 1} should align across columns: ${JSON.stringify(metrics.preparationColumns)}`)
    }
    assert.ok(left.footer && right.footer && Math.abs(left.footer.top - right.footer.top) <= 1 && Math.abs(left.footer.bottom - right.footer.bottom) <= 1,
      `${label}: preparation footers should align across columns: ${JSON.stringify(metrics.preparationColumns)}`)
  } else {
    assert.ok(metrics.evaluationPreparation.right <= metrics.viewport.width + 1 && metrics.reflectionPreparation.right <= metrics.viewport.width + 1,
      `${label}: mobile preparation content should fit the viewport: ${JSON.stringify(metrics)}`)
  }
  summary.checks.push({ name: `feedback-preparation-${label}`, metrics })
  if (screenshotName) await screenshot(page, screenshotName)
  return metrics
}

async function assertFeedbackQuestionFormReady(page, label) {
  assert.equal(await page.locator('.question-card').count(), questions.length, `${label}: all fixture questions should render after loading`)
  assert.equal(await page.locator('.evaluation-preparation, .reflection-preparation').count(), 0, `${label}: preparation panels should give way to the real question form`)
  assert.equal(await page.locator('.reflection-fields').count(), 1, `${label}: full reflection form should render after the questions`)
  assert.equal(await page.locator('.submit-box').count(), 1, `${label}: original submit section should render after the questions`)
  assert.equal(await page.getByRole('button', { name: '提交反馈' }).isDisabled(), true, `${label}: submit remains disabled until every real question is answered`)
  summary.checks.push({ name: `feedback-question-form-ready-${label}`, questionCount: questions.length, reflectionFields: true, submitDisabled: true })
}

async function fillAnswersAndReflection(page) {
  const submit = page.getByRole('button', { name: '提交反馈' })
  assert.equal(await submit.isDisabled(), true, 'submit must remain disabled before answering')

  const single = page.locator('.question-card').filter({ hasText: questions[0].question })
  await single.getByText(questions[0].options[0], { exact: true }).click()
  assert.equal(await submit.isDisabled(), true, 'submit must remain disabled with unanswered questions')
  const multiple = page.locator('.question-card').filter({ hasText: questions[1].question })
  await multiple.getByText(questions[1].options[0], { exact: true }).click()
  await multiple.getByText(questions[1].options[1], { exact: true }).click()
  await assertReadableSelection(page)
  const shortAnswer = page.locator('.question-card').filter({ hasText: questions[2].question }).locator('textarea')
  await assertElementPlusFieldFocus(page, 'feedback-question-textarea', shortAnswer, shortAnswer)
  await shortAnswer.fill('先检查来源是否覆盖问题；证据不足时应明确说明，避免补造结论。')
  assert.equal(await submit.isDisabled(), false, 'submit should enable only after all three question types are answered')

  await page.locator('.completion-row .el-switch').click()
  const timeInput = page.locator('.field-grid .el-input-number input').first()
  await assertElementPlusFieldFocus(page, 'feedback-study-time', timeInput, page.locator('.field-grid .el-input-number .el-input__wrapper'))
  await timeInput.fill('2400')
  const difficulty = page.locator('.field-grid .el-select')
  await assertElementPlusFieldFocus(page, 'feedback-difficulty', difficulty.locator('.el-select__wrapper'), difficulty.locator('.el-select__wrapper'), {
    inspector: difficulty.locator('input'), keyboardFocus: false,
  })
  const difficultyOption = page.getByRole('option', { name: '偏难', exact: true }).last()
  await difficultyOption.waitFor({ state: 'visible' })
  await difficultyOption.click()
  const rateItems = page.locator('.rating-field .el-rate__item')
  await rateItems.nth(3).click()
  const helpful = page.getByPlaceholder('例如：案例、步骤拆解、总结')
  await assertElementPlusFieldFocus(page, 'feedback-reflection-text', helpful, page.locator('.reflection-fields label').filter({ hasText: '最有帮助的内容' }).locator('.el-input__wrapper'))
  await helpful.fill('来源片段与检索步骤的示例')
  const confusing = page.getByPlaceholder('例如：术语、关键步骤或实际迁移')
  await assertElementPlusFieldFocus(page, 'feedback-reflection-confusing-text', confusing, page.locator('.reflection-fields label').filter({ hasText: '仍然困惑的地方' }).locator('.el-input__wrapper'), {
    screenshotName: 'feedback-confusing-text-focus.png',
  })
  await confusing.fill('不同来源互相矛盾时的判断顺序')
  const reflectionTextarea = page.getByPlaceholder(/可以说明你期待下一轮更强化哪些内容/)
  await assertElementPlusFieldFocus(page, 'feedback-reflection-textarea', reflectionTextarea, reflectionTextarea, { singleBorderControl: true })
  await reflectionTextarea.fill('增加两个来源冲突的案例练习。')

  return { single, multiple, shortAnswer, submit }
}

async function submitAndCheckResult(page) {
  await page.getByRole('button', { name: '提交反馈' }).click()
  await page.getByRole('heading', { name: '这次学习的回顾' }).waitFor()
  await page.locator('.el-message').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {})
  assert.equal(audit.writes.filter(item => item.path === '/api/feedback/attempts/batch/submit').length, 1)
  const submission = audit.writes.find(item => item.path === '/api/feedback/attempts/batch/submit')?.body
  assert.ok(submission, 'feedback submit API payload was not recorded')
  assert.equal(submission.learner_id, 'learner-feedback-1')
  assert.equal(submission.batch_id, 'batch-feedback-1')
  assert.equal(submission.source_resource_id, 'resource-feedback-1')
  assert.deepEqual(submission.answers.map(item => item.question_id), ['q-single', 'q-multiple', 'q-short'])
  assert.equal(submission.answers[0].answer, questions[0].options[0])
  assert.deepEqual(submission.answers[1].answer, questions[1].options.slice(0, 2))
  assert.equal(submission.answers[2].answer, '先检查来源是否覆盖问题；证据不足时应明确说明，避免补造结论。')
  assert.equal(submission.metadata.source, 'feedback_view')
  assert.equal(submission.metadata.client_version, 'web')
  assert.equal(submission.metadata.session_id, 'batch-feedback-1')
  assert.deepEqual(submission.metadata.learning_reflection, {
    completed: false, time_spent_seconds: 2400, self_rating: 4, difficulty_feeling: 'too_hard',
    helpful_part: '来源片段与检索步骤的示例', confusing_part: '不同来源互相矛盾时的判断顺序', comment: '增加两个来源冲突的案例练习。',
  })
  await page.locator('.analysis-summary .analysis-heading strong').filter({ hasText: '学习小结' }).waitFor()
  await page.locator('.capability-result-panel .analysis-heading strong').filter({ hasText: '逐题结果' }).waitFor()
  await page.getByText('纠错包巩固 + 新测评', { exact: true }).waitFor()
  await page.getByText('选择能力节点（最多 2 个）：', { exact: true }).waitFor()
  assert.equal(await page.getByText('检索策略 · 第 1 阶', { exact: true }).count(), 1)
  await resetScrollPosition(page)
  await assertTopbarVisible(page, 'desktop-result-top')
  await screenshot(page, 'feedback-result-summary-1393x871.png', false)
  await page.locator('.next-step-panel').scrollIntoViewIfNeeded()
  await assertTopbarVisible(page, 'desktop-result-next-step')
  await screenshot(page, 'feedback-result-next-step-1393x871.png', false)
  await layoutSnapshot(page, 'result-desktop-expanded')
  await assertTouchTargets(page, 'result-desktop')
  summary.checks.push({ name: 'submit-contract', payload: submission })
}

async function assertControlInViewport(page, locator, name, minHeight = 1) {
  await locator.first().scrollIntoViewIfNeeded()
  const result = await locator.evaluateAll(elements => elements.map(element => {
    const rect = element.getBoundingClientRect()
    const contentRect = document.querySelector('.content-area')?.getBoundingClientRect()
    return {
      text: element.innerText?.trim(), x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      right: rect.right, bottom: rect.bottom,
      contentTop: contentRect?.top, contentBottom: contentRect?.bottom,
      visible: rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth
        && rect.bottom > Math.max(0, contentRect?.top || 0) && rect.top < Math.min(innerHeight, contentRect?.bottom || innerHeight),
    }
  }))
  assert.ok(result.length > 0, `${name}: no controls found`)
  for (const item of result) {
    assert.ok(item.visible, `${name}: control is clipped/outside the reading viewport: ${JSON.stringify(item)}`)
    assert.ok(item.x >= -1 && item.right <= (await page.evaluate(() => innerWidth)) + 1, `${name}: horizontal clipping: ${JSON.stringify(item)}`)
    assert.ok(item.height >= minHeight, `${name}: control height ${item.height}px is below ${minHeight}px: ${JSON.stringify(item)}`)
  }
  summary.checks.push({ name, controls: result, scroll: await scrollPosition(page) })
  return result
}

async function checkMobileResultState(page) {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(60)
  await resetScrollPosition(page)
  await assertTopbarVisible(page, '390x844-result-top')
  const layout = await layoutSnapshot(page, '390x844-result-top')
  await screenshot(page, 'feedback-result-390x844-top.png', false)
  const modes = page.locator('.intent-mode-choice .el-radio-button')
  assert.equal(await modes.count(), 3, 'mobile follow-up area must expose all three learning intents')
  await assertControlInViewport(page, modes.locator('.el-radio-button__inner'), 'mobile-intent-buttons', 36)
  await assertNoTargetOverlap(page, '.intent-mode-choice .el-radio-button__inner', 'mobile intent buttons')
  const intentStates = []
  for (let index = 0; index < 3; index += 1) {
    await modes.nth(index).click()
    const state = await modes.nth(index).evaluate(element => ({ active: element.classList.contains('is-active'), text: element.innerText.trim() }))
    assert.equal(state.active, true, `mobile intent ${state.text} did not become active`)
    const generation = page.getByRole('button', { name: '生成已选资源' })
    assert.equal(await generation.isDisabled(), false, `generation should remain available for mobile intent ${state.text}`)
    intentStates.push(state)
  }
  await assertControlInViewport(page, modes.locator('.el-radio-button__inner'), 'mobile-intent-buttons-after-selection', 36)
  await assertTopbarVisible(page, '390x844-result-intent-scroll')
  await screenshot(page, 'feedback-result-390x844-intents.png', false)
  const generation = page.getByRole('button', { name: '生成已选资源' })
  const generationGeometry = await assertControlInViewport(page, generation, 'mobile-generation-button', 44)
  await assertNoTargetOverlap(page, '.next-step-panel .el-button', 'mobile next-step buttons')
  await assertTopbarVisible(page, '390x844-result-generation-scroll')
  await screenshot(page, 'feedback-result-390x844-generation.png', false)
  summary.checks.push({ name: 'mobile-result-layout', layout, intentStates, generationGeometry })
}

async function chooseFollowupAndCheckRoute(page) {
  const newNode = page.getByText('检索策略 · 第 1 阶', { exact: true })
  await newNode.click()
  const generateButton = page.getByRole('button', { name: '生成已选资源' })
  assert.equal(await generateButton.isDisabled(), true, 'removing the only selected node must disable generation')
  await newNode.click()
  assert.equal(await generateButton.isDisabled(), false)
  await generateButton.click()
  await page.getByText('已确认下一步', { exact: true }).waitFor()
  const followup = audit.writes.find(item => item.path === '/api/feedback/followups/select')?.body
  assert.ok(followup, 'follow-up selection API payload was not recorded')
  assert.equal(followup.learner_id, 'learner-feedback-1')
  assert.equal(followup.attempt_id, resultIdentity.attemptId)
  assert.equal(followup.option_id, 'custom-selection')
  assert.ok(followup.resource_types.length > 0)
  assert.equal(followup.learning_intent, 'learn_new_knowledge')
  assert.deepEqual(followup.selected_skill_node_ids, ['node-new-retrieval'])
  assert.equal(followup.next_generation_snapshot_hash, 'd'.repeat(64))
  await page.getByRole('button', { name: '查看已选资源' }).last().click()
  await page.waitForURL(url => url.pathname === '/generate' && url.searchParams.get('runId') === 'run-feedback-followup-1')
  summary.checks.push({ name: 'followup-route', pathname: new URL(page.url()).pathname, search: new URL(page.url()).search, payload: followup })
}

async function checkDesktopAndFlow() {
  const page = await openFeedbackPage({ width: 1393, height: 871 })
  try {
    assert.equal(await page.locator('.app-shell').evaluate(element => element.classList.contains('is-sidebar-collapsed')), false)
    const before = await layoutSnapshot(page, '1393x871-expanded-prestart')
    const profileSelect = page.locator('.profile-select')
    await assertElementPlusFieldFocus(page, 'feedback-profile-select', profileSelect.locator('input'), profileSelect.locator('.el-select__wrapper'), {
      screenshotName: 'feedback-profile-select-focus.png',
    })
    await chooseFilterableOptionWithKeyboard(page, profileSelect, 'RAG 工程', 'RAG 工程 / 中级', 'feedback-profile')
    const batchSelect = page.locator('.task-select')
    await assertElementPlusFieldFocus(page, 'feedback-batch-select', batchSelect.locator('input'), batchSelect.locator('.el-select__wrapper'))
    await chooseFilterableOptionWithKeyboard(page, batchSelect, '资源批次 01', '资源批次 01', 'feedback-batch')
    await assertNoTargetOverlap(page, '.task-selection .el-select, .task-selection .start-evaluation-button', 'desktop task selectors')
    await resetScrollPosition(page)
    await assertFeedbackPreparationState(page, '1393x871-desktop', { screenshotName: 'feedback-preparation-1393x871.png' })
    await assertTopbarVisible(page, 'desktop-prestart-top')
    await screenshot(page, 'feedback-1393x871-expanded-before.png')
    await page.getByRole('button', { name: '开始测评' }).click()
    await page.locator('.question-card').nth(2).waitFor()
    await assertFeedbackQuestionFormReady(page, 'desktop')
    await assertKeyboardFocus(page, '.start-evaluation-button')
    await assertTopbarVisible(page, 'desktop-after-keyboard-focus')
    await fillAnswersAndReflection(page)
    await assertTouchTargets(page, 'desktop-evaluation')
    await assertNoTargetOverlap(page, '.question-card .answer-options .el-radio, .question-card .answer-options .el-checkbox', 'desktop answer options')
    await screenshot(page, 'feedback-1393x871-expanded-evaluation.png')
    await submitAndCheckResult(page)
    await checkMobileResultState(page)
    await page.locator('.intent-mode-choice .el-radio-button').first().click()
    await page.setViewportSize({ width: 1393, height: 871 })
    await resetScrollPosition(page)
    await assertTopbarVisible(page, 'desktop-result-restored')
    await chooseFollowupAndCheckRoute(page)
  } finally { await page.close() }
}

async function checkViewport(width, height, collapsed, label) {
  const page = await openFeedbackPage({ width, height }, { collapsed })
  try {
    const data = await layoutSnapshot(page, `${label}-${width}x${height}-${collapsed ? 'collapsed' : 'expanded'}`)
    assert.equal(await page.locator('.app-shell').evaluate(element => element.classList.contains('is-sidebar-collapsed')), collapsed)
    await assertFeedbackPreparationState(page, `${label}-preparation-${width}x${height}`, {
      screenshotName: `feedback-preparation-${width}x${height}-${collapsed ? 'collapsed' : 'expanded'}.png`,
    })
    await page.getByRole('button', { name: '开始测评' }).click()
    await page.locator('.question-card').nth(2).waitFor()
    await assertFeedbackQuestionFormReady(page, label)
    await page.locator('.start-evaluation-button').scrollIntoViewIfNeeded()
    await assertTouchTargets(page, label)
    await assertNoTargetOverlap(page, '.question-card .answer-options .el-radio, .question-card .answer-options .el-checkbox', `${label} answer options`)
    const selected = page.locator('.question-card').first().locator('.el-radio').first()
    await selected.click()
    await assertReadableSelection(page)
    if (width <= 390) {
      const rightmost = await page.evaluate(() => Math.max(...[...document.querySelectorAll('.feedback-page button, .feedback-page .el-radio, .feedback-page .el-checkbox')].map(item => item.getBoundingClientRect().right).filter(Number.isFinite)))
      assert.ok(rightmost <= width + 1, `${label}: controls exceed viewport width (${rightmost}/${width})`)
    }
    await screenshot(page, `feedback-${width}x${height}-${collapsed ? 'collapsed' : 'expanded'}.png`)
    summary.checks.push({ name: label, layout: data })
  } finally { await page.close() }
}

async function checkReducedMotionViewport() {
  const page = await openFeedbackPage({ width: 390, height: 844 }, { collapsed: true, reducedMotion: true })
  try { await checkReducedMotion(page) } finally { await page.close() }
}

let thrown = null
try {
  browser = await chromium.launch(browserOptions('FEEDBACK_BROWSER_CHANNEL'))
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  serverStarted = true
  baseUrl = `http://127.0.0.1:${server.address().port}`
  await checkNoTaskAndPreStart()
  await checkDesktopAndFlow()
  await checkViewport(1331, 871, true, 'desktop-collapsed')
  await checkViewport(390, 844, true, 'phone-390')
  await checkViewport(375, 667, true, 'phone-375-short')
  await checkReducedMotionViewport()
  assert.deepEqual(audit.unexpectedApi, [], `unexpected API requests: ${JSON.stringify(audit.unexpectedApi)}`)
  assert.deepEqual(audit.externalRequests, [], `external requests: ${JSON.stringify(audit.externalRequests)}`)
  assert.deepEqual(audit.pageErrors, [], `page errors: ${JSON.stringify(audit.pageErrors)}`)
  const disallowedWrites = audit.writes.filter(item => item.allowed === false)
  assert.deepEqual(disallowedWrites, [], `unexpected writes: ${JSON.stringify(disallowedWrites)}`)
  assert.equal(audit.writes.filter(item => item.path === '/api/feedback/attempts/batch/submit').length, 1)
  assert.equal(audit.writes.filter(item => item.path === '/api/feedback/followups/select').length, 1)
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
    layoutCount: summary.layout.length,
    checkCount: summary.checks.length,
    writes: audit.writes.map(item => item.path),
    unexpectedApiCount: audit.unexpectedApi.length,
    externalRequestCount: audit.externalRequests.length,
    pageErrorCount: audit.pageErrors.length,
  }
  writeFileSync(path.join(evidenceDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
  if (browser) await browser.close()
  if (serverStarted) await new Promise(resolve => server.close(resolve))
}
if (thrown) throw thrown
