// T47 publication summary browser verification against the real production build.
//
// The page is the actual `dist` application; every `/api` call is served by an
// isolated in-process fixture. No request leaves the loopback server.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceRoot = process.env.TEST_RUN_OUTPUT
  ? path.resolve(process.env.TEST_RUN_OUTPUT)
  : path.join(frontendDir, 'tests', 'test-results', 'publication-ui')
const fixtureUser = { user_id: 'fixture-user', username: 'fixture-user', display_name: '发布汇总验收用户' }

if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before publication browser verification')
}
mkdirSync(evidenceRoot, { recursive: true })
// Keep Playwright's transient files inside this isolated test run, including
// when a sandbox rewrites TEMP before Node starts.
const browserTemp = path.join(evidenceRoot, 'tmp')
mkdirSync(browserTemp, { recursive: true })
for (const name of ['TEMP', 'TMP', 'TMPDIR']) process.env[name] = browserTemp

const consoleErrors = []
const externalRequests = []
const report = { schema_version: '1.0', suite: 'publication', cases: [], status: 'FAIL' }

function json(response, payload, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(payload))
}

function contentType(file) {
  return ({
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.png': 'image/png',
  })[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

function summary(total, published, { completeness = 'complete', pending = 0 } = {}) {
  if (completeness !== 'complete') {
    return {
      schema_version: '1.0', total, published, unpublished: null, pending_review: null,
      completeness, incomplete_reasons: ['spec_request_mismatch'],
    }
  }
  return {
    schema_version: '1.0', total, published, unpublished: total - published,
    pending_review: pending, completeness, incomplete_reasons: [],
  }
}

function profile(learnerId, name) {
  return {
    learner_id: learnerId,
    knowledge_base_id: 'track-1',
    skill_level: '中级',
    learner_type: '个人学习者',
    created_at: '2026-10-01T08:00:00Z',
    learning_preferences: { metadata: { user_profile_snapshot: { display_name: name } } },
  }
}

function resource(resourceId, runId, type, extra = {}) {
  return {
    resource_id: resourceId,
    learner_id: 'learner-1',
    run_id: runId,
    batch_id: runId,
    resource_type: type,
    resource_kind: 'learning_document',
    difficulty: '中级',
    knowledge_points: ['节点A'],
    content_text: `# ${type}\n\n固定验收内容。`,
    source_refs: [],
    publication_status: 'published',
    created_at: '2026-10-01T08:00:00Z',
    ...extra,
  }
}

function execution(runId, specId, resourceId, type, state, extra = {}) {
  return {
    run_id: runId,
    resource_spec_id: specId,
    representation: 'text',
    resource_id: resourceId,
    resource_type: type,
    resource_execution_state: state,
    publication_status: state === 'approved' ? 'published' : 'unpublished',
    attempt: 1,
    display_order: 1,
    validation_status: 'passed',
    updated_at: '2026-10-01T08:05:00Z',
    ...extra,
  }
}

function makeJob(runId, status, publishSummary, extra = {}) {
  return {
    run_id: runId,
    batch_id: runId,
    learner_id: 'learner-1',
    topic: 'T47 发布汇总验收',
    knowledge_base_id: 'track-1',
    job_status: status,
    resource_ids: [],
    resource_progress_summary: {
      schema_version: '1.0', total: publishSummary?.total ?? 3, counts: {},
      published: publishSummary?.published ?? 0, items: [],
    },
    request_payload: { learner_id: 'learner-1', topic: 'T47', resource_types: ['讲义', '实操指南', '分阶测试题'], include_review: true },
    created_at: '2026-10-01T08:00:00Z',
    finished_at: status === 'completed' || status === 'failed' ? '2026-10-01T08:20:00Z' : null,
    ...(publishSummary === undefined ? {} : { publish_summary: publishSummary }),
    ...extra,
  }
}

function initialState() {
  return {
    profiles: [profile('learner-1', '验收画像一'), profile('learner-2', '验收画像二')],
    jobsByLearner: { 'learner-1': [], 'learner-2': [] },
    executionsByRun: {},
    resourcesByRun: {},
    resourceTotals: {},
    timelines: {},
    claims: { audit_status: 'complete', resource_metrics: {} },
    sseClients: new Set(),
    requests: [],
    writes: [],
    jobDelayMs: 0,
    resourceDelayMs: 0,
    resourceFailPage: 0,
    decisionRunId: '',
    eventSequence: 0,
  }
}

let state = initialState()

function allJobs() {
  return Object.values(state.jobsByLearner).flat()
}

function findJob(runId) {
  return allJobs().find(job => job.run_id === runId)
}

function sse(response, request, runId) {
  response.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
  })
  response.flushHeaders?.()
  state.sseClients.add(response)
  const close = () => state.sseClients.delete(response)
  request.on('close', close)
  response.on('close', close)
  const events = state.timelines[runId] || []
  const job = findJob(runId)
  response.write('event: snapshot\ndata: ' + JSON.stringify({
    run_id: runId,
    job_status: job?.job_status || 'running',
    is_terminal: ['completed', 'failed'].includes(job?.job_status),
    last_event_sequence: events.length ? events.at(-1).sequence : 0,
    replay_completeness: 'complete',
  }) + '\n\n')
}

function broadcast(eventType, payload) {
  const frame = `event: ${eventType}\ndata: ${JSON.stringify(payload)}\n\n`
  for (const client of state.sseClients) client.write(frame)
}

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  if (!chunks.length) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  } catch {
    return {}
  }
}

async function apiResponse(url, method, request, response) {
  const pathname = url.pathname
  state.requests.push({ method, path: pathname, query: Object.fromEntries(url.searchParams.entries()) })

  if (pathname === '/api/auth/me' && method === 'GET') return json(response, { user: fixtureUser })
  if (pathname === '/api/profiles/' && method === 'GET') return json(response, { items: state.profiles, total: state.profiles.length })
  if (pathname === '/api/knowledge/domains' && method === 'GET') {
    return json(response, { domains: [{ domain_id: 'domain-1', name: '软件工程', tracks: [{ track_id: 'track-1', name: 'AI 应用开发' }] }] })
  }
  if (pathname === '/api/skills/nodes' && method === 'GET') {
    return json(response, { nodes: [{ node_id: '节点A', tier: 1 }, { node_id: '节点B', tier: 2 }] })
  }
  if (pathname === '/api/generate/jobs' && method === 'GET') {
    if (state.jobDelayMs) await new Promise(resolve => setTimeout(resolve, state.jobDelayMs))
    const learnerId = url.searchParams.get('learner_id')
    const items = state.jobsByLearner[learnerId] || []
    return json(response, { learner_id: learnerId, total: items.length, items: structuredClone(items) })
  }
  if (pathname === '/api/resources/courseware/jobs' && method === 'GET') return json(response, { items: [] })

  const jobMatch = pathname.match(/^\/api\/generate\/jobs\/([^/]+)$/)
  if (jobMatch && method === 'GET') {
    const job = findJob(decodeURIComponent(jobMatch[1]))
    if (!job) return json(response, { detail: '生成任务不存在' }, 404)
    return json(response, structuredClone(job))
  }

  const timelineMatch = pathname.match(/^\/api\/runs\/([^/]+)\/timeline$/)
  if (timelineMatch && method === 'GET') {
    const runId = decodeURIComponent(timelineMatch[1])
    const job = findJob(runId)
    return json(response, {
      run: {
        run_id: runId,
        status: job?.job_status === 'failed' ? 'failed' : 'completed',
        workflow_status: job?.job_status || 'completed',
        updated_at: '2026-10-01T08:20:00Z',
        replay_completeness: 'complete',
        ...(job && 'publish_summary' in job ? { publish_summary: job.publish_summary } : {}),
      },
      steps: [], events: [], checkpoints: [], evidence: [],
      resource_versions: state.resourcesByRun[runId] || [],
      reviews: [], next_event_sequence: null,
    })
  }

  const eventsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/events$/)
  if (eventsMatch && method === 'GET') return sse(response, request, decodeURIComponent(eventsMatch[1]))

  const claimsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/claims$/)
  if (claimsMatch && method === 'GET') {
    return json(response, { ...state.claims, run_id: decodeURIComponent(claimsMatch[1]) })
  }

  const decisionMatch = pathname.match(/^\/api\/resources\/items\/([^/]+)\/claim-publication-decision$/)
  if (decisionMatch && method === 'POST') {
    const resourceId = decodeURIComponent(decisionMatch[1])
    const body = await readBody(request)
    state.writes.push({ path: pathname, body })
    const publish = Boolean(body.publish)
    for (const items of Object.values(state.resourcesByRun)) {
      const target = items.find(item => item.resource_id === resourceId)
      if (!target) continue
      target.publication_status = publish ? 'published' : 'unpublished'
      target.claim_publish_decision_pending = false
      target.claim_publish_decision = publish ? 'published_by_user' : 'rejected_by_user'
      const owner = findJob(target.run_id)
      if (owner?.publish_summary) {
        const published = owner.publish_summary.published + (publish ? 1 : 0)
        owner.publish_summary = summary(owner.publish_summary.total, published)
        owner.resource_progress_summary.published = published
      }
    }
    const metric = state.claims.resource_metrics[resourceId]
    if (metric) metric.claim_publish_decision_pending = false
    return json(response, { resource: { resource_id: resourceId } })
  }

  const resourcesMatch = pathname.match(/^\/api\/resources\/([^/]+)$/)
  if (resourcesMatch && method === 'GET') {
    if (state.resourceDelayMs) await new Promise(resolve => setTimeout(resolve, state.resourceDelayMs))
    const runId = url.searchParams.get('run_id')
    const page = Number(url.searchParams.get('page') || 1)
    const pageSize = Number(url.searchParams.get('page_size') || 20)
    if (page === state.resourceFailPage) return json(response, { message: 'Synthetic resource page failure' }, 503)
    const items = state.resourcesByRun[runId] || []
    const total = state.resourceTotals[runId] ?? items.length
    return json(response, {
      learner_id: resourcesMatch[1], total, resources: items.slice((page - 1) * pageSize, page * pageSize),
      page, page_size: pageSize, has_next: page * pageSize < total,
    })
  }

  return json(response, { detail: 'Unexpected API in isolated publication fixture' }, 501)
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://publication-fixture')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    try {
      await apiResponse(url, method, request, response)
    } catch (error) {
      if (!response.headersSent) json(response, { detail: error.message }, 500)
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
  const file = safe && existsSync(candidate) && statSync(candidate).isFile()
    ? candidate : path.join(distDir, 'index.html')
  if (!existsSync(file)) {
    response.writeHead(404)
    response.end('Not found')
    return
  }
  response.writeHead(200, { 'content-type': contentType(file), 'cache-control': 'no-cache' })
  response.end(readFileSync(file))
})

function reset(next = initialState()) {
  for (const client of state.sseClients) client.end()
  state = next
  // The job projection is the page's resource-status source, so mirror the
  // seeded executions into it exactly as the backend does.
  for (const job of allJobs()) {
    const executions = state.executionsByRun[job.run_id]
    if (executions) job.resource_progress_summary.items = structuredClone(executions)
  }
  consoleErrors.length = 0
  externalRequests.length = 0
}

let activePage = null

async function newPage(browser, base, name) {
  const page = await browser.newPage({ viewport: { width: 1393, height: 871 } })
  page.setDefaultTimeout(12000)
  page.on('pageerror', error => consoleErrors.push({ case: name, message: error.message }))
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push({ case: name, message: message.text() })
  })
  page.on('request', request => {
    try {
      if (new URL(request.url()).origin !== base) externalRequests.push({ case: name, url: request.url() })
    } catch {
      externalRequests.push({ case: name, url: request.url() })
    }
  })
  await page.addInitScript(() => { localStorage.clear(); sessionStorage.clear() })
  await page.goto(base + '/generate', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.generate-page', { state: 'visible' })
  await page.waitForSelector('.task-selector', { state: 'visible' })
  activePage = page
  return page
}

async function waitForText(page, selector, expected, label = selector) {
  await page.waitForFunction(
    ([targetSelector, text]) => {
      const nodes = [...document.querySelectorAll(targetSelector)]
      return nodes.some(node => node.textContent && node.textContent.includes(text))
    },
    [selector, expected],
    { timeout: 12000 },
  ).catch(async error => {
    const actual = await page.locator(selector).first().textContent().catch(() => '<missing>')
    throw new Error(`${label}: expected to contain "${expected}", saw "${actual}" (${error.message})`)
  })
}

async function selectRun(page, runId) {
  await page.locator('.task-selector .selector-field').nth(1).locator('.el-select').click()
  await page.locator('.el-select-dropdown__item', { hasText: runId.slice(0, 8).toUpperCase() }).first().click()
  await page.waitForTimeout(120)
}

async function capture(page, name) {
  const file = path.join(evidenceRoot, `${name}.png`)
  await page.screenshot({ path: file, fullPage: false }).catch(() => {})
  return file
}

function twoOfThree(status = 'completed', { pending = false } = {}) {
  const base = initialState()
  const publishSummary = summary(3, 2, pending ? { pending: 1 } : {})
  base.jobsByLearner['learner-1'] = [makeJob('run-partial', status, publishSummary)]
  base.executionsByRun['run-partial'] = [
    execution('run-partial', 'spec-a', 'res-a', '讲义', 'approved'),
    execution('run-partial', 'spec-b', 'res-b', '实操指南', 'approved'),
    execution('run-partial', 'spec-c', pending ? 'res-c' : null, '分阶测试题', pending ? 'human_review' : 'failed', {
      publication_status: 'unpublished',
    }),
  ]
  base.resourcesByRun['run-partial'] = [
    resource('res-a', 'run-partial', '讲义', { resource_spec_id: 'spec-a' }),
    resource('res-b', 'run-partial', '实操指南', { resource_spec_id: 'spec-b' }),
  ]
  if (pending) {
    base.resourcesByRun['run-partial'].push(resource('res-c', 'run-partial', '分阶测试题', {
      resource_spec_id: 'spec-c', publication_status: 'unpublished',
      claim_publish_decision_pending: true, claim_publish_decision: 'pending',
      claim_metric_status: 'complete', claim_factual_pass_rate: 0.8,
    }))
    base.claims = {
      audit_status: 'complete',
      resource_metrics: {
        'res-c': {
          metric_status: 'complete', factual_claim_total: 5, supported_claim_total: 4,
          contradicted_claim_total: 0, not_in_evidence_claim_total: 1,
          claim_publish_decision_pending: true,
        },
      },
    }
    base.decisionRunId = 'run-partial'
  }
  return base
}

const definitions = []

definitions.push({
  id: 'publication-staggered-refresh',
  async execute(browser, base) {
    const scenario = initialState()
    scenario.jobsByLearner['learner-1'] = [makeJob('run-live', 'running', summary(3, 0))]
    scenario.executionsByRun['run-live'] = [
      execution('run-live', 'spec-a', 'res-a', '讲义', 'approved'),
      execution('run-live', 'spec-b', 'res-b', '实操指南', 'reviewing'),
      execution('run-live', 'spec-c', 'res-c', '分阶测试题', 'queued'),
    ]
    scenario.resourcesByRun['run-live'] = [resource('res-a', 'run-live', '讲义', { resource_spec_id: 'spec-a' })]
    reset(scenario)
    const page = await newPage(browser, base, 'staggered')
    await waitForText(page, '.summary-count', '0 / 3')
    await waitForText(page, '.production-status', '生成中')

    // 1/3 and then 2/3 are persisted server-side; each publication event only
    // signals a refresh, so duplicate or out-of-order delivery cannot add up.
    const job = findJob('run-live')
    job.publish_summary = summary(3, 1)
    job.resource_progress_summary.published = 1
    const first = {
      run_id: 'run-live', event_type: 'resource_published',
      sequence: ++state.eventSequence, event_sequence: state.eventSequence,
      payload: { resource_id: 'res-a' }, status: 'published',
    }
    broadcast('resource_published', first)
    await waitForText(page, '.production-status', '生成中，已发布 1/3')
    await waitForText(page, '.summary-count', '1 / 3')

    job.publish_summary = summary(3, 2)
    job.resource_progress_summary.published = 2
    const second = { ...first, sequence: ++state.eventSequence, event_sequence: state.eventSequence,
      payload: { resource_id: 'res-b' } }
    broadcast('resource_published', second)
    broadcast('resource_published', second)
    broadcast('resource_publication_decided', { ...second, event_type: 'resource_publication_decided',
      sequence: ++state.eventSequence })
    await waitForText(page, '.production-status', '生成中，已发布 2/3')
    await page.waitForTimeout(500)
    await waitForText(page, '.summary-count', '2 / 3')

    // Terminal failure keeps the real execution result and the partial count.
    job.job_status = 'failed'
    job.finished_at = '2026-10-01T08:30:00Z'
    broadcast('run_failed', { run_id: 'run-live', event_type: 'run_failed',
      sequence: ++state.eventSequence, event_sequence: state.eventSequence, payload: {} })
    await waitForText(page, '.production-status', '失败')
    await waitForText(page, '.production-status', '部分已发布（2/3）')
    await waitForText(page, '.summary-count', '2 / 3')
    return page
  },
})

definitions.push({
  id: 'publication-decision-publish',
  async execute(browser, base) {
    reset(twoOfThree('completed', { pending: true }))
    const page = await newPage(browser, base, 'decision-publish')
    await waitForText(page, '.summary-count', '2 / 3')
    await waitForText(page, '.production-status', '部分已发布（2/3）')
    await page.locator('.execution-card', { hasText: '分阶测试题' })
      .locator('button', { hasText: '审核报告' }).first().click()
    await page.locator('.claim-report-dialog').waitFor({ state: 'visible' })
    await page.locator('.claim-report-dialog').locator('button', { hasText: '确认发布' }).click()
    await waitForText(page, '.summary-count', '3 / 3')
    await waitForText(page, '.production-status', '已发布 3/3')
    assert.ok(state.writes.some(item => item.path.endsWith('/res-c/claim-publication-decision')
      && item.body.publish === true), 'the publish decision reached the fixture')
    return page
  },
})

definitions.push({
  id: 'publication-decision-rejection',
  async execute(browser, base) {
    reset(twoOfThree('completed', { pending: true }))
    const page = await newPage(browser, base, 'decision-reject')
    await waitForText(page, '.summary-count', '2 / 3')
    await page.locator('.execution-card', { hasText: '分阶测试题' })
      .locator('button', { hasText: '审核报告' }).first().click()
    await page.locator('.claim-report-dialog').waitFor({ state: 'visible' })
    await page.locator('.claim-report-dialog').locator('button', { hasText: '暂不发布' }).click()
    await page.waitForTimeout(500)
    await waitForText(page, '.summary-count', '2 / 3')
    await waitForText(page, '.production-status', '部分已发布（2/3）')
    assert.ok(state.writes.some(item => item.body.publish === false), 'the rejection reached the fixture')
    return page
  },
})

definitions.push({
  id: 'publication-read-old-version',
  async execute(browser, base) {
    const scenario = twoOfThree()
    // The current attempt failed but an earlier published version is readable.
    scenario.resourcesByRun['run-partial'].push(resource('res-c-v1', 'run-partial', '分阶测试题', {
      resource_spec_id: 'spec-c', version: 1,
    }))
    scenario.executionsByRun['run-partial'][2] = execution(
      'run-partial', 'spec-c', 'res-c-v2', '分阶测试题', 'failed', { publication_status: 'unpublished' },
    )
    reset(scenario)
    const page = await newPage(browser, base, 'old-version')
    await waitForText(page, '.summary-count', '2 / 3')
    const card = page.locator('.execution-card', { hasText: '分阶测试题' })
    await waitForText(page, '.execution-card', '已有版本已发布')
    await card.locator('button', { hasText: '查看资源' }).click()
    // The reader opens the published version by its exact id, not the failed
    // attempt and not a sibling of the same type.
    await waitForText(page, '.resource-stage', '分阶测试题')
    const stage = await page.locator('.resource-stage').first().textContent()
    assert.ok(stage.includes('固定验收内容'), 'the readable body is rendered for the opened version')
    return page
  },
})

definitions.push({
  id: 'publication-parent-linked-reading',
  async execute(browser, base) {
    const scenario = twoOfThree()
    scenario.jobsByLearner['learner-1'][0].publish_summary = summary(3, 3)
    scenario.resourcesByRun['run-partial'].push(resource('res-c-child', 'run-partial', '分阶测试题', {
      parent_resource_id: 'res-c-parent', resource_spec_id: null, resource_family_id: null,
      version: 2, content_text: '# Parent-linked published child\n\n唯一父子链阅读内容。',
    }))
    scenario.executionsByRun['run-partial'][2] = execution(
      'run-partial', 'spec-c', 'res-c-parent', '分阶测试题', 'failed', { publication_status: 'unpublished' },
    )
    reset(scenario)
    const page = await newPage(browser, base, 'parent-linked')
    await waitForText(page, '.summary-count', '3 / 3')
    const card = page.locator('.execution-card', { hasText: '分阶测试题' })
    await card.locator('button', { hasText: '查看资源' }).click()
    await waitForText(page, '.resource-stage', '唯一父子链阅读内容')
    assert.ok((await card.locator('.execution-phase').textContent()).includes('失败'), 'reading a published descendant does not approve the current attempt')
    return page
  },
})

definitions.push({
  id: 'publication-running-partial',
  async execute(browser, base) {
    const scenario = twoOfThree()
    scenario.jobsByLearner['learner-1'][0].job_status = 'running'
    scenario.jobsByLearner['learner-1'][0].publish_summary = summary(3, 1, { completeness: 'partial' })
    reset(scenario)
    const page = await newPage(browser, base, 'running-partial')
    await waitForText(page, '.production-status', '已确认 1 份已发布，汇总不完整')
    await waitForText(page, '.delivery-count', '汇总不完整')
    assert.ok(!(await page.locator('.delivery-count').textContent()).includes('/'), 'an incomplete header must not imply a verified ratio')
    return page
  },
})

definitions.push({
  id: 'publication-later-page-failure',
  expectedConsoleError: message => message.includes('503') || message === 'AxiosError',
  async execute(browser, base) {
    const scenario = initialState()
    scenario.jobsByLearner['learner-1'] = [makeJob('run-many', 'completed', summary(1, 1))]
    scenario.resourcesByRun['run-many'] = Array.from({ length: 120 }, (_, index) => resource(
      `res-page-${index}`, 'run-many', '讲义', {
        resource_spec_id: 'spec-a', version: index + 1,
        content_text: `# 分页版本 ${index}\n\n第一页已读取的版本 ${index}。`,
      },
    ))
    scenario.resourceTotals['run-many'] = 120
    scenario.resourceFailPage = 2
    reset(scenario)
    const page = await newPage(browser, base, 'later-page-failure')
    await waitForText(page, '.summary-count', '1 / 1')
    await waitForText(page, '.el-message', '已加载部分')
    await page.locator('.resource-select .el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown__item:visible')
    await options.first().waitFor({ state: 'visible' })
    assert.equal(await options.count(), 100, 'all successful first-page versions remain selectable')
    await options.last().click()
    await waitForText(page, '.resource-stage', '第一页已读取的版本 99')
    assert.ok(state.requests.some(item => item.path === '/api/resources/learner-1' && item.query.page === '2'))
    return page
  },
})

definitions.push({
  id: 'publication-old-response-fallback',
  async execute(browser, base) {
    const scenario = initialState()
    scenario.jobsByLearner['learner-1'] = [makeJob('run-legacy', 'completed', undefined)]
    scenario.executionsByRun['run-legacy'] = [execution('run-legacy', 'spec-a', 'res-a', '讲义', 'approved')]
    scenario.resourcesByRun['run-legacy'] = [resource('res-a', 'run-legacy', '讲义', { resource_spec_id: 'spec-a' })]
    reset(scenario)
    const page = await newPage(browser, base, 'legacy')
    await waitForText(page, '.production-status', '已完成')
    const status = await page.locator('.production-status').first().textContent()
    assert.ok(!status.includes('汇总不完整'), 'a legacy response is not labelled as an incomplete summary')
    assert.ok(!status.includes('部分已发布'), 'a legacy response never claims partial publication')
    return page
  },
})

definitions.push({
  id: 'publication-pagination',
  async execute(browser, base) {
    const scenario = initialState()
    scenario.jobsByLearner['learner-1'] = [makeJob('run-many', 'completed', summary(120, 120))]
    scenario.resourcesByRun['run-many'] = Array.from({ length: 120 }, (_, index) => resource(
      `res-${String(index).padStart(3, '0')}`, 'run-many', index % 2 ? '讲义' : '实操指南',
      { resource_spec_id: `spec-${index}`, version: index + 1 },
    ))
    scenario.resourceTotals['run-many'] = 120
    reset(scenario)
    const page = await newPage(browser, base, 'pagination')
    await waitForText(page, '.summary-count', '120 / 120')
    await page.waitForTimeout(600)
    const reads = state.requests.filter(item => item.path === '/api/resources/learner-1')
    const pages = new Set(reads.map(item => item.query.page))
    assert.ok(pages.size >= 2, `expected several resource pages, saw ${reads.length} reads over ${[...pages]}`)
    const loaded = await page.locator('.resource-select .el-select__wrapper').count()
    assert.ok(loaded > 0, 'the resource selector is available after pagination')
    return page
  },
})

definitions.push({
  id: 'publication-slow-switch',
  async execute(browser, base) {
    const scenario = twoOfThree()
    scenario.jobsByLearner['learner-1'].push(makeJob('run-single', 'completed', summary(1, 1)))
    scenario.resourcesByRun['run-single'] = [resource('res-single', 'run-single', '讲义', { resource_spec_id: 'spec-s' })]
    scenario.executionsByRun['run-single'] = [execution('run-single', 'spec-s', 'res-single', '讲义', 'approved')]
    scenario.resourceDelayMs = 900
    reset(scenario)
    const page = await newPage(browser, base, 'switch')
    await waitForText(page, '.summary-count', '2 / 3')
    await selectRun(page, 'run-single')
    await waitForText(page, '.summary-count', '1 / 1')
    // The delayed response for the previous run arrives after the switch; it
    // must not overwrite the newly selected run.
    await page.waitForTimeout(1200)
    await waitForText(page, '.summary-count', '1 / 1')
    await waitForText(page, '.production-status', '已发布 1/1')
    return page
  },
})

definitions.push({
  id: 'publication-partial-unknown',
  async execute(browser, base) {
    const scenario = twoOfThree()
    scenario.jobsByLearner['learner-1'][0].publish_summary = summary(3, 2, { completeness: 'partial' })
    reset(scenario)
    const page = await newPage(browser, base, 'partial')
    await waitForText(page, '.production-status', '已确认 2 份已发布，汇总不完整')
    await waitForText(page, '.summary-count', '2 / 3')
    return page
  },
})

definitions.push({
  id: 'publication-failed-zero',
  async execute(browser, base) {
    const scenario = initialState()
    scenario.jobsByLearner['learner-1'] = [makeJob('run-empty', 'failed', summary(3, 0))]
    scenario.executionsByRun['run-empty'] = [
      execution('run-empty', 'spec-a', null, '讲义', 'failed'),
      execution('run-empty', 'spec-b', null, '实操指南', 'failed'),
      execution('run-empty', 'spec-c', null, '分阶测试题', 'failed'),
    ]
    reset(scenario)
    const page = await newPage(browser, base, 'failed-zero')
    await waitForText(page, '.production-status', '失败')
    await waitForText(page, '.production-status', '任务已结束，暂无已发布资源')
    await waitForText(page, '.summary-count', '0 / 3')
    const readCount = state.requests.filter(item => item.path === '/api/resources/learner-1').length
    assert.equal(readCount, 0, 'a failed run without readable output issues no resource read')
    return page
  },
})

definitions.push({
  id: 'publication-reentry',
  async execute(browser, base) {
    reset(twoOfThree())
    const page = await newPage(browser, base, 'reentry')
    await waitForText(page, '.summary-count', '2 / 3')
    // Re-entering the task re-reads persisted facts instead of reusing a first
    // terminal snapshot.
    const job = findJob('run-partial')
    job.publish_summary = summary(3, 3)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.generate-page', { state: 'visible' })
    await waitForText(page, '.summary-count', '3 / 3')
    await waitForText(page, '.production-status', '已发布 3/3')
    return page
  },
})

async function runCase(browser, base, definition) {
  const started = Date.now()
  const entry = { id: definition.id, status: 'FAIL', duration_ms: 0 }
  let page
  try {
    page = await definition.execute(browser, base)
    const unexpected = consoleErrors.filter(error => !definition.expectedConsoleError?.(error.message))
    assert.deepEqual(unexpected, [], 'unexpected browser errors')
    assert.deepEqual(externalRequests, [], 'the fixture must not access external services')
    entry.status = 'PASS'
    if (page) entry.screenshot = await capture(page, definition.id)
  } catch (error) {
    entry.error = error.message
    const evidencePage = page || activePage
    if (evidencePage && !evidencePage.isClosed()) {
      entry.failure_screenshot = await capture(evidencePage, definition.id + '-failure')
      entry.console = consoleErrors.slice(-8)
      entry.requests = state.requests.slice(-30)
      entry.cards = await evidencePage.locator('.execution-card').allTextContents().catch(() => [])
    }
  } finally {
    entry.console_errors = consoleErrors.filter(error => !definition.expectedConsoleError?.(error.message))
    entry.expected_console_errors = consoleErrors.filter(error => definition.expectedConsoleError?.(error.message))
    entry.external_requests = [...externalRequests]
    activePage = null
    if (page) await page.close().catch(() => {})
    entry.duration_ms = Date.now() - started
    report.cases.push(entry)
  }
}

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${server.address().port}`
  let browser
  try {
    browser = await chromium.launch(browserOptions('T47_BROWSER_CHANNEL'))
    for (const definition of definitions) await runCase(browser, base, definition)
  } finally {
    if (browser) await browser.close().catch(() => {})
    await new Promise(resolve => server.close(resolve))
  }
  const failed = report.cases.filter(item => item.status !== 'PASS')
  report.external_requests = report.cases.flatMap(entry => entry.external_requests).slice(0, 20)
  report.console_errors = report.cases.flatMap(entry => entry.console_errors).slice(0, 20)
  report.status = failed.length ? 'FAIL' : 'PASS'
  report.failure = failed[0]?.error || null
  writeFileSync(path.join(evidenceRoot, 'publication-summary.json'), JSON.stringify(report, null, 2) + '\n')
  if (failed.length) {
    console.error(failed.map(item => `${item.id}: ${item.error}`).join('\n'))
    process.exitCode = 1
  }
  console.log(`publicationSummaryBrowser: ${report.status} (${report.cases.length} cases)`)
}

main().catch(error => {
  report.failure = error.message
  writeFileSync(path.join(evidenceRoot, 'publication-summary.json'), JSON.stringify(report, null, 2) + '\n')
  console.error(error)
  process.exitCode = 1
})
