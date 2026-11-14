import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'
import { inspectElementSelect } from './selectPresentation.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const batchSelectorOnly = process.argv.includes('--batch-selector')
const assessmentOnly = process.argv.includes('--assessment')
const alignmentOnly = process.argv.includes('--assessment-alignment')
const resultRoutesOnly = process.argv.includes('--result-routes')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', alignmentOnly ? 'feedback-alignment-ui' : assessmentOnly ? 'feedback-assessment-ui' : batchSelectorOnly ? 'feedback-batch-ui' : 'feedback-ui')
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
    question_results: currentScenario === 'summary-only' ? [] : questions.map((question, index) => ({
      question_id: question.question_id, question_type: question.question_type,
      correct: index === 0, score: index === 0 ? 30 : 21, max_score: index === 0 ? 30 : 35,
      knowledge_point: question.knowledge_point, skill_node_id: question.skill_node_id,
    })),
    next_step_recommendation: {
      title: '默认建议：纠错包巩固',
      description: '本轮处于强化区间，默认先用纠错包巩固本次薄弱点；也可以从当前学习阶选择可学习节点。',
      recommended_action: 'correction_package', default_new_node_ids: [], default_review_node_ids: ['node-grounding'],
      alternative_action: 'learn_new_and_reinforce', alternative_learning_intent: 'learn_new_and_reinforce',
      alternative_learning_node_ids: ['node-new-retrieval', 'node-grounding'],
      alternative_new_node_ids: ['node-new-retrieval'], alternative_review_node_ids: ['node-grounding'],
      alternative_learning_title: '一新一旧学习',
      alternative_learning_description: '兼顾推进与巩固：学习一个新节点，同时复习一个已学习但未完全掌握的节点。',
    },
    cross_tier_review_pairs: {
      'node-cross-new': ['node-cross-review'],
      'node-other-new': ['node-other-review'],
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
    analysis: currentScenario === 'summary-only' ? null : {
      summary: '你能识别检索步骤，继续练习证据与回答的对应关系会更稳固。',
      reflection_insight: '你提到希望多练习核对步骤，下一轮会围绕这个目标安排内容。',
      profile_update_suggestions: [], learner_suggestions: ['提交回答前逐项核对来源。'],
      report_highlights: ['已完成三道测评题。'], analysis_status: ['completed-batch', 'confirmed-batch'].includes(currentScenario) ? 'llm' : 'fallback',
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
      learn_new_knowledge: [
        candidate('node-new-retrieval', '检索策略', 'unlearned', 1),
        candidate('node-new-ranking', '排序策略', 'unlearned', 2),
        { ...candidate('node-blocked', '待解锁节点', 'unlearned', 3), blocked_by_node_ids: ['node-grounding'] },
      ],
      cross_tier_new_knowledge: [
        { ...candidate('node-cross-new', '跨阶检索', 'unlearned', 1), tier: 2 },
        { ...candidate('node-other-new', '跨阶排序', 'unlearned', 2), tier: 2 },
      ],
      cross_tier_prerequisite_review: [
        candidate('node-cross-review', '检索前置', 'learned', 1),
        candidate('node-other-review', '排序前置', 'learned', 2),
      ],
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
    if (method === 'GET' && url.pathname === '/api/skills/nodes') {
      assert.equal(url.searchParams.get('knowledge_base_id'), 'kb-feedback')
      if (currentScenario === 'nodes-unavailable') return writeJson(res, { message: 'nodes unavailable' }, 503)
      return writeJson(res, { nodes: [{ node_id: 'node-retrieval', name: currentScenario === 'long-node' ? '证据检索与文档解析及可追溯来源的多节点学习目标'.repeat(3) : '证据检索' }] })
    }
    if (method === 'GET' && url.pathname === `/api/resources/${learnerId}`) {
      return writeJson(res, { resources: currentScenario === 'no-task' ? [] : [fixtureResource()] })
    }
    if (method === 'GET' && url.pathname === '/api/generate/jobs') {
      const items = currentScenario === 'no-task' ? [] : [{
        run_id: 'run-feedback-1', batch_id: 'batch-feedback-1', learner_id: learnerId,
        job_status: 'completed', status: 'completed', created_at: '2026-10-01T08:00:00Z',
        finished_at: '2026-10-01T08:06:00Z', request_payload: { resource_types: ['讲义'], target_skill_nodes: ['node-retrieval'] },
      }]
      return writeJson(res, { items, total: items.length })
    }
    if (method === 'GET' && url.pathname === '/api/generate/capabilities') {
      return writeJson(res, { round_creation_enabled: !['round-disabled', 'reinforce-only'].includes(currentScenario) })
    }
    if (method === 'GET' && url.pathname === '/api/feedback/rounds/next/candidates') {
      if (url.searchParams.get('learner_id') !== learnerId || url.searchParams.get('source_attempt_id') !== resultIdentity.attemptId) {
        return writeJson(res, { detail: 'ROUND_SELECTION_INVALID' }, 404)
      }
      const generation = feedbackResult(null).generation_options
      if (currentScenario === 'reinforce-only') {
        return writeJson(res, {
          profile_version: 2,
          generation_options: { ...generation, learn_new_knowledge: [], learning_candidates: [] },
          eligible_review_nodes: [], correction_targets: [],
        })
      }
      return writeJson(res, {
        profile_version: 2, generation_options: { ...generation, learning_candidates: [
          candidate('node-grounding', '证据核验', 'learned', 1),
          { ...candidate('node-foundation', '来源标注', 'unlearned', 2), prerequisite_ids: ['node-grounding', 'hidden-node'] },
        ] }, correction_targets: [],
        eligible_review_nodes: generation.reinforce_weakness,
      })
    }
    if (method === 'GET' && url.pathname === `/api/feedback/results/${learnerId}`) {
      if (['advance-result', 'long-result'].includes(currentScenario)) {
        const result = feedbackResult(null)
        result.decision.action = 'advance'
        result.feedback_report.total_score = 92
        result.feedback_report.score_rate = .92
        result.feedback_report.next_step_recommendation.recommended_action = 'learn_new'
        result.feedback_report.next_step_recommendation.learning_intent = 'learn_new_knowledge'
        result.analysis.summary = '本轮测评得分92分，检索与证据核验表现稳定，已达到推进条件。六道题中有一道需要巩固，建议回顾证据与回答之间的对应关系，并检查来源是否足以覆盖问题。遇到资料不足时，先说明证据边界，再考虑调整检索方式。'
        result.analysis.reflection_insight = '本轮投入30分钟，学习节奏与难度匹配。可以回看失分题，核对你给出的排查步骤是否完整，再用一句话复述检索流程。'
        result.analysis.learner_suggestions = ['回顾失分题，检查是否遗漏关键步骤。', '复述从输入查询到核对来源的检索流程。', '遇到资料不足时，明确说明证据边界。']
        result.feedback_report.question_results.push(...result.feedback_report.question_results.map(question => ({ ...question, question_id: question.question_id + '-extra' })))
        if (currentScenario === 'long-result') {
          result.analysis.summary = result.analysis.summary.repeat(12)
          result.feedback_report.question_results = Array.from({ length: 24 }, (_, index) => ({
            ...result.feedback_report.question_results[index % 6], question_id: `long-${index}`,
          }))
        }
        return writeJson(res, [result])
      }
      return writeJson(res, ['round-disabled', 'reinforce-only', 'completed-batch', 'confirmed-batch', 'summary-only'].includes(currentScenario) ? [feedbackResult(null, currentScenario === 'confirmed-batch')] : [])
    }
    if (method === 'GET' && url.pathname === `/api/feedback/evaluation/batch/${learnerId}/batch-feedback-1`) {
      return writeJson(res, {
        learner_id: learnerId, batch_id: 'batch-feedback-1', topic: 'RAG 检索与证据核验',
        resource_ids: ['resource-feedback-1'], total: currentScenario === 'alignment' ? 6 : questions.length,
        questions: currentScenario === 'alignment' ? [...questions, ...questions.map(question => ({ ...question, question_id: question.question_id + '-extra' }))] : questions,
      })
    }
    if (method === 'POST' && url.pathname === '/api/feedback/attempts/batch/submit') {
      audit.writes.push({ path: url.pathname, body })
      return writeJson(res, feedbackResult(body))
    }
    if (method === 'POST' && url.pathname === '/api/feedback/rounds/next/select') {
      audit.writes.push({ path: url.pathname, body })
      return writeJson(res, {
        schema_version: '1.0', round_id: 'round-feedback-1', stage_id: 'stage-feedback-1',
        primary_node_id: body.primary_node_id, primary_default_run_id: 'run-feedback-followup-1',
        members: [
          { member_id: 'primary-feedback-1', node_id: body.primary_node_id, role: 'primary', job_ids: ['run-feedback-followup-1'] },
          { member_id: 'review-feedback-1', node_id: body.review_node_id, role: 'review', job_ids: ['run-feedback-review-1'] },
        ],
      }, 202)
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

async function assertBatchStatusPresentation(select) {
  const metrics = await select.locator('.batch-selected-label').evaluate(element => {
    const badge = element.querySelector('.batch-status')
    const text = element.querySelector('.batch-label-text')
    return {
      rightGap: element.getBoundingClientRect().right - badge.getBoundingClientRect().right,
      overlap: text.getBoundingClientRect().right > badge.getBoundingClientRect().left,
      shadow: getComputedStyle(badge).boxShadow,
    }
  })
  assert.ok(Math.abs(metrics.rightGap) <= 1, 'feedback status should stay at the right edge')
  assert.equal(metrics.overlap, false, 'batch description must not overlap status')
  assert.notEqual(metrics.shadow, 'none', 'status should have a raised glass edge')
}

async function checkBatchNodeFallback() {
  const page = await openFeedbackPage({ width: 1393, height: 871 }, { scenario: 'nodes-unavailable' })
  try {
    assert.equal(await page.locator('.task-select .batch-node-name').innerText(), 'node-retrieval')
    assert.equal(await page.locator('.start-evaluation-button').isEnabled(), true)
    await assertBatchStatusPresentation(page.locator('.task-select'))
  } finally { await page.close() }
}

async function checkBatchSelector() {
  for (const width of [1393, 390]) {
    for (const scenario of ['active', 'completed-batch', 'confirmed-batch', 'summary-only', 'long-node']) {
      const page = await openFeedbackPage({ width, height: 871 }, { scenario, collapsed: width < 500 })
      try {
        const select = page.locator('.task-select')
        await select.locator('.batch-node-name').waitFor()
        assert.ok((await select.locator('.batch-node-name').innerText()).startsWith('证据检索'))
        assert.equal(await select.locator('.batch-status').innerText(), ['completed-batch', 'confirmed-batch', 'summary-only'].includes(scenario) ? '已反馈' : '待反馈')
        await assertBatchStatusPresentation(select)
        await chooseFilterableOptionWithKeyboard(page, select, '证据检索', '资源批次 01', `batch-${width}-${scenario}`)
        await assertBatchStatusPresentation(select)
        await inspectElementSelect({ page, suite: 'feedback-batch', evidenceDir, id: `batch-${scenario}`, select, getWriteCount: () => audit.writes.length })
        const bounds = await select.boundingBox()
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'batch selector must fit the viewport')
        await screenshot(page, `batch-${width}-${scenario}.png`, false)
        if (['completed-batch', 'confirmed-batch'].includes(scenario)) await assertReviewSections(page, width, scenario === 'confirmed-batch')
        if (scenario === 'confirmed-batch') await assertConfirmedFollowup(page, width)
        if (scenario === 'summary-only') {
          assert.equal(await page.locator('.review-card').count(), 0)
          assert.equal(await page.locator('.capability-result-panel .result-score strong').innerText(), '72')
          assert.equal(await page.locator('.capability-result-list').count(), 0)
          assert.equal(await page.locator('.next-step-verdict .result-action-label').innerText(), '强化练习')
          assert.ok((await page.locator('.next-step-verdict p').innerText()).includes('证据检索已有基础'))
        }
        summary.checks.push({ name: `batch-selector-${width}-${scenario}`, passed: true })
      } finally { await page.close() }
    }
  }
  await checkBatchNodeFallback()
  assert.equal(audit.writes.length, 0, 'batch selection must not submit feedback or create tasks')
}

async function assertReviewSections(page, width, confirmed = false) {
  const metrics = await page.locator('#feedback-report').evaluate(root => {
    const box = selector => root.querySelector(selector).getBoundingClientRect().toJSON()
    const analysis = box('.analysis-summary')
    const questions = box('.capability-result-panel')
    const next = box('.next-step-panel')
    return {
      analysis, questions, next,
      headings: [...root.querySelectorAll('.analysis-heading strong, #feedback-next-step')].map(node => node.textContent.trim()),
      analysisBorder: getComputedStyle(root.querySelector('.analysis-summary')).borderTopWidth,
      questionsBorder: getComputedStyle(root.querySelector('.capability-result-panel')).borderTopWidth,
    }
  })
  assert.deepEqual(metrics.headings, ['学习小结', '逐题结果', confirmed ? '下一步学习' : '选择下一步学习方案'])
  assert.equal(await page.locator('.review-card').count(), 0, 'standalone overview should be removed')
  assert.equal(await page.locator('.analysis-summary .result-action-label').count(), 0, 'action conclusions belong to the next learning section')
  assert.equal(await page.locator('.next-step-verdict .result-action-label').innerText(), '强化练习')
  assert.equal(await page.locator('.capability-result-panel .result-score strong').innerText(), '72')
  assert.equal(await page.locator('#feedback-report .review-section-symbol svg').count(), 3, 'section headings should use icons instead of repeating question numbers')
  if (width > 1100) {
    assert.ok(Math.abs(metrics.analysis.top - metrics.questions.top) < 1, 'desktop review cards should share a row')
    assert.ok(metrics.questions.left >= metrics.analysis.right + 12, 'desktop review cards should have a visible gutter')
  } else {
    assert.ok(metrics.questions.top >= metrics.analysis.bottom + 12, 'mobile review cards should be stacked with a gutter')
  }
  assert.ok(metrics.next.top >= Math.max(metrics.analysis.bottom, metrics.questions.bottom) + 12, 'next learning section must have its own boundary')
  for (const box of [metrics.analysis, metrics.questions, metrics.next]) {
    assert.ok(box.left >= 0 && box.right <= width + 1, 'review sections should fit the viewport')
  }
  assert.equal(metrics.analysisBorder, '1px')
  assert.equal(metrics.questionsBorder, '1px')
  const filename = `review-sections-${width}${confirmed ? '-confirmed' : ''}.png`
  await page.locator('.result-details').screenshot({ path: path.join(evidenceDir, filename), animations: 'disabled' })
  summary.screenshots.push(filename)
  summary.checks.push({ name: `review-sections-${width}`, metrics })
}

async function assertConfirmedFollowup(page, width) {
  const card = page.locator('.selected-followup-card')
  assert.equal(await card.locator('.selected-followup-status').innerText(), '已确认下一步')
  assert.equal(await card.locator('h4').innerText(), '当前阶学习')
  assert.deepEqual(await card.locator('.selected-target-chip').allTextContents(), ['检索策略'])
  const geometry = await card.evaluate(element => {
    const main = element.querySelector('.selected-followup-main').getBoundingClientRect().toJSON()
    const action = element.querySelector('.selected-followup-action').getBoundingClientRect().toJSON()
    return { main, action, overflow: element.scrollWidth > element.clientWidth }
  })
  assert.equal(geometry.overflow, false)
  if (width > 760) assert.ok(geometry.action.left >= geometry.main.right - 1, 'confirmed action should be a distinct right column')
  else assert.ok(geometry.action.top >= geometry.main.bottom - 1, 'confirmed action should follow the learning goals on mobile')
  const filename = `confirmed-followup-${width}.png`
  await card.screenshot({ path: path.join(evidenceDir, filename), animations: 'disabled' })
  summary.screenshots.push(filename)
  await page.evaluate(() => {
    const router = document.querySelector('#app').__vue_app__.config.globalProperties.$router
    router.beforeEach(to => { window.__confirmedNavigation = { path: to.path, query: to.query }; return false })
  })
  await card.getByRole('button', { name: '查看已选资源' }).click()
  await page.waitForFunction(() => window.__confirmedNavigation?.path === '/generate')
  const navigation = await page.evaluate(() => ({
    route: window.__confirmedNavigation,
    runId: localStorage.getItem('current_generation_run_id'),
    runIds: JSON.parse(localStorage.getItem('current_generation_run_ids')),
  }))
  assert.deepEqual(navigation.route, { path: '/generate', query: { runId: 'run-feedback-followup-1', learnerId: 'learner-feedback-1' } })
  assert.equal(navigation.runId, 'run-feedback-followup-1')
  assert.deepEqual(navigation.runIds, ['run-feedback-followup-1'])
  summary.checks.push({ name: `confirmed-followup-${width}`, geometry, navigation })
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
  await page.locator('.study-time-stepper .el-input-number__increase').click()
  assert.equal(await timeInput.inputValue(), '2700')
  await page.locator('.study-time-stepper .el-input-number__decrease').click()
  assert.equal(await timeInput.inputValue(), '2400')
  const difficulty = page.locator('.field-grid .el-select')
  await assertElementPlusFieldFocus(page, 'feedback-difficulty', difficulty.locator('.el-select__wrapper'), difficulty.locator('.el-select__wrapper'), {
    inspector: difficulty.locator('input'), keyboardFocus: false,
  })
  const difficultyOption = page.getByRole('option', { name: '偏难', exact: true }).last()
  await difficultyOption.waitFor({ state: 'visible' })
  await difficultyOption.click()
  const rateItems = page.locator('.rating-field .el-rate__item')
  await rateItems.nth(3).click()
  assert.equal(await page.getByText('最有帮助的内容', { exact: true }).count(), 0)
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
  await page.getByRole('heading', { name: /学习小结/ }).waitFor()
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
    confusing_part: '不同来源互相矛盾时的判断顺序', comment: '增加两个来源冲突的案例练习。',
  })
  await page.locator('.analysis-summary .analysis-heading strong').filter({ hasText: '学习小结' }).waitFor()
  await page.locator('.capability-result-panel .analysis-heading strong').filter({ hasText: '逐题结果' }).waitFor()
  await page.getByText('纠错包巩固 + 新测评', { exact: true }).waitFor()
  await page.getByRole('radiogroup', { name: '下一步学习路线' }).getByText('下一轮学习', { exact: true }).click()
  await page.getByText('主节点（选 1 个）', { exact: true }).waitFor()
  assert.equal(await page.getByText('一新一旧', { exact: true }).count(), 0)
  assert.equal(await page.locator('.result-score strong').innerText(), '72')
  assert.ok(await page.locator('.result-details').evaluate(element =>
    Boolean(element.compareDocumentPosition(document.querySelector('.next-step-panel')) & Node.DOCUMENT_POSITION_FOLLOWING)
  ), 'the detailed review should precede the learning options')
  const choices = page.locator('.plan-options .followup-choice')
  assert.deepEqual(await choices.locator('h4').allTextContents(), ['纠错包巩固 + 新测评', '下一轮学习'])
  assert.equal(await choices.locator('button').count(), 2, 'each learning option should have its own action')
  assert.equal(await choices.filter({ has: page.getByText('系统推荐', { exact: true }) }).locator('h4').innerText(), '纠错包巩固 + 新测评')
  assert.equal(await choices.filter({ visible: true }).count(), 1)
  const layout = await page.locator('.result-details').evaluate(element => {
    const [summary, questions] = [...element.children].map(child => child.getBoundingClientRect())
    return { stacked: questions.top >= summary.bottom, indicator: getComputedStyle(document.querySelector('.nav-item.is-active'), '::before').content }
  })
  assert.deepEqual(layout, { stacked: false, indicator: 'none' })
  const nodeGroup = page.getByRole('combobox', { name: '主节点', exact: true })
  await nodeGroup.press('ArrowDown')
  assert.equal(await page.getByRole('option', { name: /待解锁节点/ }).count(), 0)
  assert.equal(await page.getByText('巩固旧节点', { exact: true }).count(), 0)
  await page.getByRole('option', { name: /排序策略 · 第/ }).click()
  await nodeGroup.press('ArrowDown')
  assert.equal(await page.getByRole('option', { name: /排序策略 · 第/ }).getAttribute('aria-selected'), 'true')
  await page.getByRole('option', { name: /检索策略 · 第/ }).click()
  assert.ok((await page.locator('.next-round-review .el-select').innerText()).includes('不附带复习'))
  assert.equal(await page.getByRole('combobox', { name: '副节点', exact: true }).count(), 1)
  const recommendationContrast = await contrastRatio(page.locator('#feedback-next-step'))
  assert.ok(recommendationContrast.ratio >= 4.5, `recommendation title contrast: ${recommendationContrast.ratio.toFixed(2)}:1`)
  summary.checks.push({ name: 'recommendation-title-contrast', ...recommendationContrast })
  assert.equal(await page.getByText(/检索策略 · 第/).filter({ visible: true }).count(), 1)
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
  assert.equal(await page.getByRole('radiogroup', { name: '主节点学习方式' }).count(), 0)
  const primary = page.getByRole('combobox', { name: '主节点', exact: true })
  await primary.press('ArrowDown')
  assert.equal(await page.getByRole('option', { name: /来源标注 · 第/ }).count(), 0)
  await page.keyboard.press('Escape')
  await assertControlInViewport(page, page.locator('.next-round-field .el-select__wrapper').first(), 'mobile-primary-node', 36)
  await assertTopbarVisible(page, '390x844-result-intent-scroll')
  await screenshot(page, 'feedback-result-390x844-intents.png', false)
  const generation = page.getByRole('button', { name: '生成下一轮已选资源' })
  const generationGeometry = await assertControlInViewport(page, generation, 'mobile-generation-button', 44)
  await assertNoTargetOverlap(page, '.next-step-panel .el-button', 'mobile next-step buttons')
  await assertTopbarVisible(page, '390x844-result-generation-scroll')
  await screenshot(page, 'feedback-result-390x844-generation.png', false)
  summary.checks.push({ name: 'mobile-result-layout', layout, generationGeometry })
}

async function chooseFollowupAndCheckRoute(page) {
  await page.getByRole('group', { name: '主节点资源' }).getByText('案例分析', { exact: true }).click()
  await page.getByRole('button', { name: '生成下一轮已选资源' }).click()
  await page.waitForURL(url => url.pathname === '/generate' && url.searchParams.get('roundId') === 'round-feedback-1'
    && url.searchParams.get('memberId') === 'primary-feedback-1' && url.searchParams.get('runId') === 'run-feedback-followup-1')
  assert.equal(await page.locator('.nav-item.is-active').evaluate(node => getComputedStyle(node, '::before').content), 'none')
  const followup = audit.writes.find(item => item.path === '/api/feedback/rounds/next/select')?.body
  assert.ok(followup, 'next round selection payload was not recorded')
  assert.equal(followup.learner_id, 'learner-feedback-1')
  assert.equal(followup.source_attempt_id, resultIdentity.attemptId)
  assert.equal(followup.primary_node_id, 'node-grounding')
  assert.equal(followup.primary_learning_intent, 'reinforce_weakness')
  assert.equal(followup.review_node_id, null)
  assert.deepEqual(followup.primary_resource_types, ['讲义', '实操指南', '分阶测试题', '案例分析'])
  assert.match(followup.selection_key, /^round-next-/)
  assert.equal('selected_skill_node_ids' in followup, false)
  summary.checks.push({ name: 'followup-route', pathname: new URL(page.url()).pathname, search: new URL(page.url()).search, payload: followup })
}

async function checkRoundDisabled() {
  const page = await openFeedbackPage({ width: 390, height: 844 }, { scenario: 'round-disabled' })
  try {
    assert.equal(await page.getByRole('radiogroup', { name: '下一步学习路线' }).getByRole('radio', { name: '纠错巩固' }).isChecked(), true)
    await page.getByRole('radiogroup', { name: '下一步学习路线' }).getByText('下一轮学习', { exact: true }).click()
    await page.getByText('候选节点可预览。当前环境未启用下一轮学习创建。', { exact: true }).waitFor()
    const nodes = page.getByRole('combobox', { name: '主节点', exact: true })
    assert.equal(await nodes.isEnabled(), true)
    assert.equal(await page.getByRole('radiogroup', { name: '主节点学习方式' }).count(), 0)
    await nodes.press('ArrowDown')
    await page.getByRole('option', { name: /证据核验 · 第/ }).click()
    assert.equal(await page.locator('.next-round-preview strong').innerText(), '证据核验')
    assert.equal(await page.getByRole('button', { name: '生成下一轮已选资源' }).count(), 0)
    await page.getByRole('radiogroup', { name: '下一步学习路线' }).getByText('纠错巩固', { exact: true }).click()
    assert.equal(await page.getByRole('button', { name: '生成纠错包与新测评' }).isEnabled(), true)
  } finally { await page.close() }
}

async function checkResultRoutes() {
  const page = await openFeedbackPage({ width: 1651, height: 871 }, { scenario: 'advance-result', collapsed: true })
  try {
    const routes = page.getByRole('radiogroup', { name: '下一步学习路线' })
    const learning = routes.getByRole('radio', { name: '下一轮学习' })
    const correction = routes.getByRole('radio', { name: '纠错巩固' })
    const node = page.getByRole('combobox', { name: '主节点', exact: true })
    await node.waitFor()
    assert.equal(await learning.isChecked(), true)
    assert.equal(await page.locator('.verdict-recommendation').innerText(), '系统推荐 · 下一轮学习')
    const geometry = await page.locator('.content-area').evaluate(el => ({
      scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
      bottom: el.querySelector('.next-step-panel').getBoundingClientRect().bottom,
    }))
    assert.ok(geometry.scrollHeight <= geometry.clientHeight + 1, JSON.stringify(geometry))
    await screenshot(page, 'result-route-learning-1651.png', false)
    await node.press('ArrowDown')
    await page.getByRole('option', { name: /排序策略 · 第/ }).click()
    await routes.getByText('纠错巩固', { exact: true }).click()
    assert.equal(await correction.isChecked(), true)
    assert.equal(await node.count(), 0)
    assert.equal(await page.getByRole('button', { name: '生成纠错包与新测评' }).isVisible(), true)
    assert.ok(await page.locator('.content-area').evaluate(el => el.scrollHeight <= el.clientHeight + 1))
    await screenshot(page, 'result-route-correction-1651.png', false)
    await routes.getByText('下一轮学习', { exact: true }).click()
    await node.press('ArrowDown')
    assert.equal(await page.getByRole('option', { name: /排序策略 · 第/ }).getAttribute('aria-selected'), 'true')
    await page.keyboard.press('Escape')
    await checkMobileResultState(page)
  } finally { await page.close() }
  const longPage = await openFeedbackPage({ width: 1651, height: 871 }, { scenario: 'long-result', collapsed: true })
  try {
    await longPage.getByRole('heading', { name: '逐题结果' }).waitFor()
    const scroll = await longPage.locator('.content-area').evaluate(element => {
      const regions = [...element.querySelectorAll('.analysis-content, .question-results-content')]
      const headerTops = regions.map(region => region.previousElementSibling.getBoundingClientRect().top)
      const panel = element.querySelector('.next-step-panel')
      const panelBottom = panel.getBoundingClientRect().bottom
      for (const region of regions) region.scrollTop = region.scrollHeight
      return {
        contentOverflow: element.scrollHeight - element.clientHeight,
        panelBottom,
        bottomGap: element.getBoundingClientRect().bottom - panelBottom,
        regions: regions.map((region, index) => ({
          top: region.scrollTop,
          headerShift: region.previousElementSibling.getBoundingClientRect().top - headerTops[index],
        })),
      }
    })
    assert.ok(scroll.contentOverflow <= 1 && scroll.bottomGap >= 0 && scroll.bottomGap <= 32, JSON.stringify(scroll))
    assert.equal(scroll.regions.length, 2)
    assert.ok(scroll.regions.every(region => region.top > 0 && region.headerShift === 0), JSON.stringify(scroll))
    summary.checks.push({ name: 'result-independent-overflow', ...scroll })
  } finally { await longPage.close() }
  await checkRoundDisabled()
  const reinforcePage = await openFeedbackPage({ width: 1651, height: 871 }, { scenario: 'reinforce-only' })
  try {
    await reinforcePage.getByRole('radiogroup', { name: '下一步学习路线' }).getByText('下一轮学习', { exact: true }).click()
    await reinforcePage.getByRole('combobox', { name: '主节点', exact: true }).press('ArrowDown')
    await reinforcePage.getByRole('option', { name: /证据核验 · 第/ }).waitFor()
    assert.equal(await reinforcePage.getByRole('button', { name: '生成下一轮已选资源' }).count(), 0)
  } finally { await reinforcePage.close() }
  assert.equal(audit.writes.length, 0)
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
    assert.equal(await batchSelect.locator('.batch-node-name').innerText(), '证据检索')
    assert.equal(await batchSelect.locator('.batch-status').innerText(), '待反馈')
    await assertBatchStatusPresentation(batchSelect)
    await assertElementPlusFieldFocus(page, 'feedback-batch-select', batchSelect.locator('input'), batchSelect.locator('.el-select__wrapper'))
    await chooseFilterableOptionWithKeyboard(page, batchSelect, '证据检索', '资源批次 01', 'feedback-batch')
    await assertNoTargetOverlap(page, '.task-selection .el-select, .task-selection .start-evaluation-button', 'desktop task selectors')
    await inspectElementSelect({
      page, suite: 'feedback', evidenceDir, id: 'feedback-batch-desktop',
      select: batchSelect, getWriteCount: () => audit.writes.length,
    })
    await page.setViewportSize({ width: 390, height: 844 })
    await assertBatchStatusPresentation(batchSelect)
    await inspectElementSelect({
      page, suite: 'feedback', evidenceDir, id: 'feedback-batch-mobile',
      select: batchSelect, getWriteCount: () => audit.writes.length,
    })
    await page.setViewportSize({ width: 1393, height: 871 })
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

async function checkIndependentAssessment() {
  for (const width of [1393, 390, 375]) {
    const page = await openFeedbackPage({ width, height: 871 }, { collapsed: width < 500 })
    try {
      await page.getByRole('button', { name: '开始测评' }).click()
      await page.locator('.question-card').last().waitFor()
      await assertFeedbackQuestionFormReady(page, `assessment-${width}`)
      assert.equal(await page.getByRole('button', { name: '需要提示' }).count(), 0)
      assert.equal(await page.locator('.tutor-panel, .tutor-usage-row').count(), 0)
      const radio = page.getByRole('radio', { name: questions[0].options[0], exact: true })
      await radio.focus()
      await radio.press('Space')
      assert.equal(await radio.isChecked(), true)
      await fillAnswersAndReflection(page)
      const options = await page.locator('.answer-options .el-radio, .answer-options .el-checkbox').evaluateAll(elements => elements.map(element => ({
        shadow: getComputedStyle(element).boxShadow,
        right: element.getBoundingClientRect().right,
        left: element.getBoundingClientRect().left,
      })))
      assert.ok(options.every(option => option.shadow !== 'none' && option.left >= 0 && option.right <= width + 1))
      // A tall capture viewport keeps the entire panel clear of the fixed app
      // header; interaction and overflow checks above still use height 871.
      await page.setViewportSize({ width, height: 2600 })
      await page.locator('.evaluation-panel').screenshot({ path: path.join(evidenceDir, `assessment-questions-${width}.png`), animations: 'disabled' })
      await page.locator('.reflection-panel').screenshot({ path: path.join(evidenceDir, `assessment-reflection-${width}.png`), animations: 'disabled' })
      summary.screenshots.push(`assessment-questions-${width}.png`, `assessment-reflection-${width}.png`)
      await page.setViewportSize({ width, height: 871 })
      const before = audit.writes.length
      await page.getByRole('button', { name: '提交反馈' }).click()
      await page.locator('#feedback-report').waitFor()
      assert.equal(audit.writes.length, before + 1)
      const submission = audit.writes.at(-1).body
      assert.deepEqual(submission.answers.map(answer => answer.answer), [questions[0].options[0], questions[1].options.slice(0, 2), '先检查来源是否覆盖问题；证据不足时应明确说明，避免补造结论。'])
      assert.equal(submission.hint_count, 0)
      assert.equal(submission.metadata.learning_reflection.time_spent_seconds, 2400)
      assert.equal(Object.hasOwn(submission.metadata.learning_reflection, 'helpful_part'), false)
      assert.equal(submission.metadata.learning_reflection.difficulty_feeling, 'too_hard')
      assert.equal(submission.metadata.learning_reflection.completed, false)
      assert.equal(submission.metadata.learning_reflection.self_rating, 4)
      assert.equal(submission.metadata.learning_reflection.comment, '增加两个来源冲突的案例练习。')
      summary.checks.push({ name: `independent-assessment-${width}`, options, submitted: true })
    } finally { await page.close() }
  }
  assert.equal(audit.requests.filter(request => request.path.startsWith('/api/tutor/')).length, 0)
  assert.equal(audit.writes.filter(write => write.path === '/api/feedback/attempts/batch/submit').length, 3)
}

async function checkAssessmentAlignment() {
  for (const [width, reducedMotion] of [[1651, false], [1651, true], [390, true]]) {
    const page = await openFeedbackPage({ width, height: 871 }, { scenario: 'alignment', collapsed: true, reducedMotion })
    try {
      await page.getByRole('button', { name: '开始测评' }).click()
      await page.waitForFunction(() => document.querySelectorAll('.question-card').length === 6)
      await page.evaluate(async () => {
        let previous = null
        let stable = 0
        for (let frame = 0; frame < 150 && stable < 6; frame++) {
          await new Promise(requestAnimationFrame)
          const top = document.querySelector('.evaluation-panel').getBoundingClientRect().top
          stable = previous !== null && Math.abs(top - previous) < .2 ? stable + 1 : 0
          previous = top
        }
      })
      const geometry = await page.locator('.feedback-workspace').evaluate(element => {
        const evaluation = element.querySelector('.evaluation-panel').getBoundingClientRect().toJSON()
        const reflection = element.querySelector('.reflection-panel').getBoundingClientRect().toJSON()
        return { evaluation, reflection, delta: reflection.top - evaluation.top }
      })
      const filename = `alignment-${width}-${reducedMotion ? 'reduced' : 'smooth'}.png`
      await screenshot(page, filename, false)
      summary.checks.push({ name: `assessment-alignment-${width}-${reducedMotion}`, geometry })
      if (width > 960) {
        assert.ok(Math.abs(geometry.delta) <= 1, `assessment columns should align after starting: ${JSON.stringify(geometry)}`)
        assert.ok(geometry.reflection.bottom <= 871, `reflection panel should fit before scrolling: ${geometry.reflection.bottom}`)
        const bottomDelta = await page.locator('.feedback-workspace').evaluate(element => {
          const scroller = element.closest('.content-area')
          scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'instant' })
          const evaluationBottom = element.querySelector('.evaluation-panel').getBoundingClientRect().bottom
          const reflectionBottom = element.querySelector('.reflection-panel').getBoundingClientRect().bottom
          return reflectionBottom - evaluationBottom
        })
        summary.checks.push({ name: `assessment-bottom-alignment-${width}-${reducedMotion}`, bottomDelta })
        assert.ok(Math.abs(bottomDelta) <= 1, `assessment columns should align at the end: ${bottomDelta}`)
      }
      else assert.ok(geometry.reflection.top >= geometry.evaluation.bottom, 'mobile panels should stay stacked')
      assert.equal(await page.getByRole('button', { name: '提交反馈' }).isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '需要提示' }).count(), 0)
    } finally { await page.close() }
  }
  assert.equal(audit.writes.length, 0)
}

let thrown = null
try {
  browser = await chromium.launch(browserOptions('FEEDBACK_BROWSER_CHANNEL'))
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  serverStarted = true
  baseUrl = `http://127.0.0.1:${server.address().port}`
  if (resultRoutesOnly) {
    await checkResultRoutes()
  } else if (alignmentOnly) {
    await checkAssessmentAlignment()
  } else if (assessmentOnly) {
    await checkIndependentAssessment()
  } else if (batchSelectorOnly) {
    await checkBatchSelector()
  } else {
  await checkNoTaskAndPreStart()
  await checkBatchNodeFallback()
  await checkDesktopAndFlow()
  await checkRoundDisabled()
  await checkViewport(1331, 871, true, 'desktop-collapsed')
  await checkViewport(390, 844, true, 'phone-390')
  await checkViewport(375, 667, true, 'phone-375-short')
  await checkReducedMotionViewport()
  }
  assert.deepEqual(audit.unexpectedApi, [], `unexpected API requests: ${JSON.stringify(audit.unexpectedApi)}`)
  assert.deepEqual(audit.externalRequests, [], `external requests: ${JSON.stringify(audit.externalRequests)}`)
  assert.deepEqual(audit.pageErrors, [], `page errors: ${JSON.stringify(audit.pageErrors)}`)
  const disallowedWrites = audit.writes.filter(item => item.allowed === false)
  assert.deepEqual(disallowedWrites, [], `unexpected writes: ${JSON.stringify(disallowedWrites)}`)
  if (!batchSelectorOnly && !assessmentOnly && !alignmentOnly && !resultRoutesOnly) {
    assert.equal(audit.writes.filter(item => item.path === '/api/feedback/attempts/batch/submit').length, 1)
    assert.equal(audit.writes.filter(item => item.path === '/api/feedback/rounds/next/select').length, 1)
  }
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
