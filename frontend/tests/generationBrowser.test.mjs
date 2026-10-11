import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const reportDir = path.join(frontendDir, 'tests', 'test-results', 'generation-ui')
const baseViewport = { width: 1393, height: 871 }
const fixtureUser = { user_id: 'fixture-user', username: 'fixture-user', display_name: '资源生产验收用户' }
const externalRequests = []
const browserErrors = []
const fixtureAudit = { requests: [], writes: [], unexpectedApi: [] }

if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before generation browser verification')
}
mkdirSync(reportDir, { recursive: true })

function profile(learnerId, displayName, directionId = 'track-1') {
  return {
    learner_id: learnerId,
    knowledge_base_id: directionId,
    skill_level: '中级',
    learner_type: '个人学习者',
    created_at: '2026-10-01T08:00:00Z',
    learning_preferences: { metadata: { user_profile_snapshot: { display_name: displayName } } },
  }
}

function resource(resourceId, learnerId, runId, type, kind = 'learning_document', content = '# 内容\n\n固定的验收材料。', extra = {}) {
  return {
    resource_id: resourceId,
    learner_id: learnerId,
    run_id: runId,
    batch_id: 'batch-1',
    resource_type: type,
    resource_kind: kind,
    topic: type + '主题',
    title: type + '验收资源',
    difficulty: '中级',
    knowledge_points: ['节点A', '节点B'],
    content_text: content,
    created_at: '2026-10-01T08:00:00Z',
    file_path: '/fixture/resources/' + resourceId + '.md',
    source_refs: [],
    ...extra,
  }
}

function execution(resourceSpecId, resourceId, type, status, extra = {}) {
  return {
    run_id: 'run-main',
    resource_spec_id: resourceSpecId,
    representation: 'text',
    resource_id: resourceId,
    resource_type: type,
    resource_execution_state: status,
    publication_status: status === 'approved' ? 'published' : 'unpublished',
    attempt: 1,
    display_order: 1,
    ...extra,
  }
}

function timelineEvents(runId, count = 5) {
  return Array.from({ length: count }, (_, index) => ({
    run_id: runId,
    event_id: 'evt-' + runId + '-' + (index + 1),
    sequence: index + 1,
    event_type: index % 2 ? 'step_succeeded' : 'step_started',
    step_id: 'step-' + (index + 1),
    step_sequence: index + 1,
    node_name: 'agent_' + (index + 1),
    agent_name: '学习资源 Agent ' + (index + 1),
    action: '生成与核验',
    status: index % 2 ? 'success' : 'running',
    input_summary: '根据来源快照处理任务 ' + (index + 1),
    output_summary: '已完成工作流阶段 ' + (index + 1) + '。'.repeat(1),
    payload: {},
  }))
}

function makeJob(learnerId, runId, status = 'completed', overrides = {}) {
  const resourceTypes = ['讲义', '实操指南', '分阶测试题']
  return {
    run_id: runId,
    batch_id: 'batch-' + learnerId,
    learner_id: learnerId,
    job_status: status,
    status,
    created_at: '2026-10-01T08:00:00Z',
    finished_at: status === 'completed' ? '2026-10-01T08:06:00Z' : null,
    error_message: status === 'failed' ? '验收任务故障说明：可重新生成。' : null,
    request_payload: {
      learner_id: learnerId,
      resource_types: resourceTypes,
      include_review: true,
      include_claim_check: true,
      constraints: { continuation_instructions: '按原任务参数重试。' },
    },
    resource_progress_summary: { total: 3, completed: status === 'completed' ? 3 : 1, published: status === 'completed' ? 2 : 0, failed: 0 },
    ...overrides,
  }
}

function longMarkdown() {
  const paragraphs = Array.from({ length: 55 }, (_, index) => (
    '## 学习材料段落 ' + String(index + 1).padStart(2, '0') + '\n\n'
    + ('在冻结来源上建立清晰解释，保留概念、步骤与证据之间的关系。 ').repeat(9)
  ))
  paragraphs.push('## 末尾段落\n\n这是滚动到正文末尾后应当完整可读的标记。')
  return '# 长篇学习材料\n\n' + paragraphs.join('\n\n')
}

function scenarioState(name) {
  const profiles = name === 'no-profile' ? [] : [
    profile('learner-1', '林知行'),
    profile('learner-2', '周明远', 'track-2'),
  ]
  const long = name === 'long'
  const primaryStatus = name === 'queued' ? 'queued'
    : name === 'running' || name === 'sse-fallback' ? 'running'
      : name === 'failed' ? 'failed' : 'completed'
  const primaryRun = name === 'multi' ? 'run-one' : 'run-main'
  const jobsByLearner = {
    'learner-1': name === 'no-task' || name === 'no-profile' ? [] : [
      makeJob('learner-1', primaryRun, name === 'multi' ? 'running' : primaryStatus, name === 'no-output' ? {
        resource_progress_summary: { total: 3, completed: 3, published: 0, failed: 0 },
      } : {}),
    ],
    'learner-2': name === 'multi' ? [makeJob('learner-2', 'run-alt', 'completed', {
      batch_id: 'batch-learner-2',
      request_payload: { learner_id: 'learner-2', resource_types: ['复习清单'], include_review: true, include_claim_check: false },
    })] : [],
  }
  if (name === 'multi') {
    jobsByLearner['learner-1'].push(makeJob('learner-1', 'run-queued', 'queued', { batch_id: 'batch-learner-1-queued' }))
  }
  const resourcesByRun = {
    [primaryRun]: ['no-task', 'no-profile', 'no-output', 'queued'].includes(name) ? [] : [
      resource('resource-guide', 'learner-1', primaryRun, long ? '多阶段知识迁移与证据核验实操指南资源类型' : '实操指南', 'learning_document', long ? longMarkdown() : '# 实操指南\n\n从验收来源中完成一个可复核步骤。', {
        claim_publish_decision_pending: name === 'claim-pending',
      }),
      resource('resource-checklist', 'learner-1', primaryRun, '复习清单', 'learning_document', '# 复习清单\n\n回忆关键概念并核对证据。'),
      resource('resource-lecture', 'learner-1', primaryRun, '讲义'),
    ],
    'run-alt': [
      resource('resource-alt', 'learner-2', 'run-alt', '复习清单'),
    ],
    'run-queued': [],
  }
  const executionsByRun = {
    [primaryRun]: ['no-output', 'queued'].includes(name) ? [] : [
      execution('spec-guide', 'resource-guide', '实操指南', name === 'partial' ? 'revision_requested' : 'approved', {
        error_message: name === 'partial' ? '审核要求再次生成此资源。' : '',
        agent_name: long ? '资源生成与跨阶段证据核验协作 Agent' : undefined,
        validation_status: long ? '来源快照与发布范围一致性及学习目标覆盖校验通过' : undefined,
        claim_metric_status: 'complete',
        factual_claim_total: 5,
        supported_claim_total: 4,
        not_in_evidence_claim_total: 1,
        claim_factual_pass_rate: 0.8,
        claim_publish_decision_pending: name === 'claim-pending',
      }),
      execution('spec-checklist', 'resource-checklist', '复习清单', 'approved', { display_order: 2 }),
      execution('spec-lecture', 'resource-lecture', '讲义', name === 'partial' ? 'failed' : 'approved', {
        display_order: 3,
        error_message: name === 'partial' ? '验收故障：该资源生成失败。' : '',
      }),
    ],
    'run-alt': [execution('spec-alt', 'resource-alt', '复习清单', 'approved')],
    'run-queued': [],
  }
  const longCourseware = name === 'courseware-long'
  const coursewareJob = {
    run_id: 'cw-existing',
    learner_id: 'learner-1',
    source_batch_id: 'batch-learner-1',
    status: 'failed',
    title: '验收互动课件',
    created_at: '2026-10-01T08:20:00Z',
    updated_at: '2026-10-01T08:21:00Z',
    error_message: '验收课件故障，可重试。',
    request_options: { learning_goal: '掌握核心步骤', expected_duration_minutes: 30 },
    scenes: longCourseware
      ? Array.from({ length: 32 }, (_, index) => ({
        scene_id: 'scene-long-' + index,
        scene_order: index,
        title: '长课件场景 ' + String(index + 1).padStart(2, '0'),
        kind: index % 2 ? 'practice' : 'review',
        status: 'failed',
        attempt: 1,
      }))
      : [{ scene_id: 'scene-failed', scene_order: 0, title: '失败页面', kind: 'practice', status: 'failed', attempt: 1 }],
    warnings: longCourseware
      ? Array.from({ length: 16 }, (_, index) => ({
        code: 'fixture-long-warning-' + index,
        message: '长课件警告 ' + String(index + 1).padStart(2, '0'),
      }))
      : [],
  }
  const timelineCount = long ? 90 : name === 'running' ? 8 : 5
  return {
    scenario: name,
    profiles,
    jobsByLearner,
    coursewareJobs: ['courseware-existing', 'courseware-long'].includes(name) ? [coursewareJob] : [],
    coursewareJob,
    resourcesByRun,
    executionsByRun,
    timelines: {
      [primaryRun]: timelineEvents(primaryRun, timelineCount),
      'run-alt': timelineEvents('run-alt', 6),
      'run-queued': [],
      'cw-existing': [],
    },
    sseMode: name === 'sse-fallback' ? 'stream_error' : 'normal',
    writes: [],
    requests: [],
    unexpectedApi: [],
    failureMessages: [],
    statusFailureCount: 0,
    resourceFailureCount: 0,
    resourceDelayMs: 0,
    jobsDelayMs: 0,
    timelineDelayMs: 0,
    sseClients: new Set(),
    nextRun: 0,
    lastClaimDecision: null,
    claims: {
      claims: [
        { claim_id: 'claim-1', resource_id: 'resource-guide', claim_type: 'factual', claim_text: '验收事实陈述。' },
      ],
      judgements: [
        { claim_id: 'claim-1', verdict: 'not_in_evidence', reason: ' fixture 缺少直接证据。' },
      ],
      resource_metrics: {
        'resource-guide': {
          metric_status: 'complete',
          factual_claim_total: 5,
          supported_claim_total: 4,
          not_in_evidence_claim_total: 1,
          contradicted_claim_total: 0,
          claim_warning_publish: false,
          claim_publish_decision_pending: true,
        },
      },
    },
  }
}

let state = scenarioState('completed')
const evidence = {
  scenarios: [],
  screenshots: [],
  layoutChecks: [],
  scrollChecks: [],
  interactionChecks: [],
  contrastChecks: [],
  motionChecks: [],
  errors: browserErrors,
  externalRequests,
}

function json(response, payload, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(payload))
}

async function readBody(request) {
  let body = ''
  for await (const chunk of request) body += chunk
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    return { __invalid_json: body }
  }
}

function allJobs() {
  return Object.values(state.jobsByLearner).flat()
}

function findJob(runId) {
  return allJobs().find((item) => item.run_id === runId)
}

function recordWrite(record) {
  state.writes.push(record)
  fixtureAudit.writes.push({ scenario: state.scenario, ...record })
}

function recordUnexpected(record) {
  state.unexpectedApi.push(record)
  fixtureAudit.unexpectedApi.push({ scenario: state.scenario, ...record })
}

function eventSource(response, request, runId) {
  response.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
  })
  response.flushHeaders?.()
  const clients = state.sseClients
  const close = () => clients.delete(response)
  request.on('close', close)
  response.on('close', close)
  state.sseClients.add(response)
  if (state.sseMode === 'stream_error') {
    response.write('event: stream_error\ndata: ' + JSON.stringify({ code: 'WORKFLOW_STREAM_UNAVAILABLE' }) + '\n\n')
    return
  }
  const events = state.timelines[runId] || []
  const job = findJob(runId)
  const terminal = ['completed', 'failed'].includes(job?.job_status)
  response.write('event: snapshot\ndata: ' + JSON.stringify({
    run_id: runId,
    run_status: job?.job_status || 'running',
    is_terminal: terminal,
    last_event_sequence: events.at(-1)?.sequence || 0,
    replay_completeness: 'complete',
  }) + '\n\n')
  for (const event of events.slice(-4)) {
    response.write('event: ' + event.event_type + '\ndata: ' + JSON.stringify(event) + '\n\n')
  }
  if (terminal) response.end()
}

function coursewarePath(pathname) {
  const match = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/detail$/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function apiResponse(url, method, request, response) {
  const pathname = url.pathname
  const requestRecord = { method, path: pathname, query: Object.fromEntries(url.searchParams.entries()) }
  state.requests.push(requestRecord)
  fixtureAudit.requests.push({ scenario: state.scenario, ...requestRecord })

  if (pathname === '/api/auth/me' && method === 'GET') return json(response, { user: fixtureUser })
  if (pathname === '/api/profiles/' && method === 'GET') return json(response, { items: state.profiles, total: state.profiles.length })
  const profileDelete = pathname.match(/^\/api\/profiles\/([^/]+)$/)
  if (profileDelete && method === 'DELETE') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.profiles = state.profiles.filter((item) => item.learner_id !== decodeURIComponent(profileDelete[1]))
    return json(response, { learner_id: decodeURIComponent(profileDelete[1]), deleted: true })
  }
  if (pathname === '/api/knowledge/domains' && method === 'GET') {
    return json(response, { domains: [{ domain_id: 'domain-1', name: '软件工程', tracks: [
      { track_id: 'track-1', name: 'AI 应用开发' },
      { track_id: 'track-2', name: '数据工程' },
    ] }] })
  }
  if (pathname === '/api/skills/nodes' && method === 'GET') {
    return json(response, { nodes: [{ node_id: '节点A', tier: 1 }, { node_id: '节点B', tier: 2 }] })
  }
  if (pathname === '/api/generate/jobs' && method === 'GET') {
    if (state.jobsDelayMs) await new Promise((resolve) => setTimeout(resolve, state.jobsDelayMs))
    return json(response, { items: state.jobsByLearner[url.searchParams.get('learner_id')] || [] })
  }
  if (pathname === '/api/resources/courseware/jobs' && method === 'GET') {
    return json(response, { items: state.coursewareJobs.filter((item) => item.learner_id === url.searchParams.get('learner_id')) })
  }
  if (pathname === '/api/resource-library/learner-1' && method === 'GET') {
    const items = Object.values(state.resourcesByRun).flat().filter((item) => item.learner_id === 'learner-1')
    return json(response, items.map(({ resource_id, ...item }) => ({ ...item, id: resource_id })))
  }
  const coursewareDetailId = coursewarePath(pathname)
  if (coursewareDetailId && method === 'GET') {
    return json(response, { ...state.coursewareJob, run_id: coursewareDetailId })
  }
  if (pathname === '/api/tutor/sessions' && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    return json(response, { ...body, session_id: 'tutor-fixture-session', status: 'active' })
  }
  if (pathname === '/api/generate/jobs' && method === 'POST') {
    recordUnexpected({ method, path: pathname, reason: 'GenerateView has no initial-job creation entry' })
    return json(response, { detail: 'Unexpected initial generation POST in /generate fixture' }, 501)
  }
  const continuationMatch = pathname.match(/^\/api\/resources\/batches\/([^/]+)\/continuations$/)
  if (continuationMatch && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    const runId = 'continue-' + (++state.nextRun)
    const created = makeJob(body.learner_id || 'learner-1', runId, 'queued', {
      batch_id: decodeURIComponent(continuationMatch[1]),
      request_payload: { ...body, include_review: true },
      resource_progress_summary: { total: (body.resource_types || []).length, completed: 0, published: 0, failed: 0 },
    })
    ;(state.jobsByLearner[created.learner_id] ||= []).unshift(created)
    state.timelines[runId] = []
    state.executionsByRun[runId] = []
    return json(response, { run_id: runId, job_status: 'queued' })
  }
  const decisionMatch = pathname.match(/^\/api\/resources\/items\/([^/]+)\/claim-publication-decision$/)
  if (decisionMatch && method === 'POST') {
    const body = await readBody(request)
    state.lastClaimDecision = { resource_id: decodeURIComponent(decisionMatch[1]), body }
    recordWrite({ method, path: pathname, body })
    state.claims.resource_metrics[state.lastClaimDecision.resource_id] = {
      ...state.claims.resource_metrics[state.lastClaimDecision.resource_id],
      claim_publish_decision_pending: false,
    }
    return json(response, { resource_id: state.lastClaimDecision.resource_id, published: Boolean(body.publish) })
  }
  const coursewareBatchPath = '/api/resources/courseware/jobs/batch'
  if (pathname === coursewareBatchPath && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    const runId = 'courseware-created-' + (++state.nextRun)
    state.coursewareJob = {
      run_id: runId,
      learner_id: body.learner_id,
      source_batch_id: 'batch-' + body.learner_id,
      status: 'composing',
      title: '新增互动课件',
      created_at: '2026-10-09T08:00:00Z',
      updated_at: '2026-10-09T08:00:00Z',
      request_options: { learning_goal: body.learning_goal, expected_duration_minutes: body.expected_duration_minutes },
      scenes: [{ scene_id: 'scene-new', scene_order: 0, title: '验收页面', kind: 'practice', status: 'composing', attempt: 1 }],
      warnings: [],
    }
    state.coursewareJobs.unshift(state.coursewareJob)
    return json(response, { jobs: [state.coursewareJob] })
  }
  const coursewareRetryMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/retry$/)
  if (coursewareRetryMatch && method === 'POST') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.coursewareJob = { ...state.coursewareJob, status: 'composing', error_message: '' }
    return json(response, { status: 'composing' })
  }
  const sceneRetryMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/scenes\/([^/]+)\/retry$/)
  if (sceneRetryMatch && method === 'POST') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.coursewareJob = {
      ...state.coursewareJob,
      status: 'composing',
      scenes: state.coursewareJob.scenes.map((scene) => ({ ...scene, status: 'retry_queued' })),
    }
    return json(response, { status: 'retry_queued' })
  }
  const timelineMatch = pathname.match(/^\/api\/runs\/([^/]+)\/timeline$/)
  if (timelineMatch && method === 'GET') {
    if (state.timelineDelayMs) await new Promise((resolve) => setTimeout(resolve, state.timelineDelayMs))
    const runId = decodeURIComponent(timelineMatch[1])
    const events = state.timelines[runId] || []
    return json(response, {
      run: { run_id: runId, status: findJob(runId)?.job_status || 'completed' },
      events: events.filter((event) => event.sequence > Number(url.searchParams.get('after_sequence') || 0)),
      resource_executions: state.executionsByRun[runId] || [],
      next_event_sequence: null,
      replay_completeness: 'complete',
    })
  }
  const resourceDetailMatch = pathname.match(/^\/api\/resources\/items\/([^/]+)$/)
  if (resourceDetailMatch && method === 'GET') {
    const resourceId = decodeURIComponent(resourceDetailMatch[1])
    const resourceItem = Object.values(state.resourcesByRun).flat().find((item) => item.resource_id === resourceId)
    return resourceItem ? json(response, { resource: resourceItem }) : json(response, { detail: 'Unknown fixture resource' }, 404)
  }
  const claimsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/claims$/)
  if (claimsMatch && method === 'GET') return json(response, state.claims)
  const statusMatch = pathname.match(/^\/api\/generate\/jobs\/([^/]+)$/)
  if (statusMatch && method === 'GET') {
    if (state.statusFailureCount > 0) {
      state.statusFailureCount -= 1
      return json(response, {}, 503)
    }
    const job = findJob(decodeURIComponent(statusMatch[1]))
    return job ? json(response, job) : json(response, { detail: 'Unknown fixture run' }, 404)
  }
  const resourceFileMatch = pathname.match(/^\/api\/resources\/file\/([^/]+)$/)
  if (resourceFileMatch && method === 'GET') {
    const resourceId = decodeURIComponent(resourceFileMatch[1])
    response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'content-disposition': 'inline; filename="' + resourceId + '.md"', 'cache-control': 'no-store' })
    response.end('Isolated fixture download for ' + resourceId)
    return
  }
  const resourceListMatch = pathname.match(/^\/api\/resources\/([^/]+)$/)
  if (resourceListMatch && method === 'GET') {
    if (state.resourceDelayMs) await new Promise((resolve) => setTimeout(resolve, state.resourceDelayMs))
    if (state.resourceFailureCount > 0) {
      state.resourceFailureCount -= 1
      return json(response, {}, 503)
    }
    const learnerId = decodeURIComponent(resourceListMatch[1])
    const runId = url.searchParams.get('run_id') || ''
    const resources = runId
      ? (state.resourcesByRun[runId] || [])
      : Object.values(state.resourcesByRun).flat()
    return json(response, { resources: resources.filter((item) => item.learner_id === learnerId) })
  }
  const runEventsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/events$/)
  if (runEventsMatch && method === 'GET') return eventSource(response, request, decodeURIComponent(runEventsMatch[1]))
  const coursewareEventsMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/events$/)
  if (coursewareEventsMatch && method === 'GET') {
    const runId = decodeURIComponent(coursewareEventsMatch[1])
    response.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' })
    const clients = state.sseClients
    const close = () => clients.delete(response)
    request.on('close', close)
    response.on('close', close)
    clients.add(response)
    response.write('event: courseware_progress\ndata: ' + JSON.stringify({ run_id: runId, status: state.coursewareJob.status }) + '\n\n')
    return
  }
  if (pathname === '/api/learning-history/learner-1/journey' && method === 'GET') {
    return json(response, { learner_id: 'learner-1', profile: state.profiles[0] || null, rounds: [], events: [], current_state: { current_nodes: [], completed_nodes: [] }, next_offset: null })
  }
  if (pathname === '/api/onboarding/questions' && method === 'GET') return json(response, { questions: [] })
  if (pathname === '/api/resources/learner-1' && method === 'GET') {
    return json(response, { resources: (state.resourcesByRun['run-main'] || []) })
  }

  recordUnexpected({ method, path: pathname })
  return json(response, { detail: 'Unexpected API in isolated generation fixture' }, 501)
}

function contentType(file) {
  return ({
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  })[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://generation-fixture')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/__fixture/scenario/')) {
    state = scenarioState(decodeURIComponent(url.pathname.split('/').at(-1)))
    response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' })
    response.end('scenario reset')
    return
  }
  if (url.pathname.startsWith('/api/')) {
    try {
      await apiResponse(url, method, request, response)
    } catch (error) {
      recordUnexpected({ method, path: url.pathname, reason: error.message })
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

function resetScenario(name) {
  for (const response of state.sseClients) response.end()
  state = scenarioState(name)
  externalRequests.length = 0
  browserErrors.length = 0
}

async function newPage(browser, base, name, viewport = baseViewport, options = {}) {
  resetScenario(name)
  if (options.delayJobsMs) state.jobsDelayMs = options.delayJobsMs
  if (options.failStatus) state.statusFailureCount = options.failStatus
  if (options.failResources) state.resourceFailureCount = options.failResources
  if (options.delayResourcesMs) state.resourceDelayMs = options.delayResourcesMs
  if (options.delayTimelineMs) state.timelineDelayMs = options.delayTimelineMs
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: options.reducedMotion ? 'reduce' : 'no-preference',
  })
  page.setDefaultTimeout(9000)
  page.setDefaultNavigationTimeout(15000)
  page.on('pageerror', (error) => browserErrors.push({ scenario: name, message: error.message }))
  page.on('request', (request) => {
    try {
      if (new URL(request.url()).origin !== base) externalRequests.push({ scenario: name, url: request.url(), method: request.method() })
    } catch {
      externalRequests.push({ scenario: name, url: request.url(), method: request.method() })
    }
  })
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  await page.goto(base + '/generate', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.generate-page', { state: 'visible' })
  await page.locator('.task-selector').waitFor({ state: 'visible' })
  await page.waitForTimeout(100)
  return page
}

async function waitForLayout(page, expectedFit = null) {
  await page.waitForFunction((fit) => {
    const root = document.querySelector('.generate-page')
    if (!root || root.classList.contains('is-layout-measuring')) return false
    if (document.querySelector('.app-shell.is-sidebar-animating')) return false
    return fit === null || root.classList.contains('is-fit-layout') === fit
  }, expectedFit, { timeout: 9000 })
  await page.waitForTimeout(50)
}

async function setSidebar(page, collapsed) {
  const current = await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed'))
  if (current !== collapsed) {
    await page.locator('.sidebar-toggle').click()
    await page.waitForFunction((expected) => {
      const shell = document.querySelector('.app-shell')
      return shell?.classList.contains('is-sidebar-collapsed') === expected
        && !shell.classList.contains('is-sidebar-animating')
    }, collapsed)
  }
  await waitForLayout(page, true)
}

async function geometry(page, label, requireFit = false) {
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const root = document.querySelector('.generate-page')
    const content = document.querySelector('.content-area')
    const studio = document.querySelector('.studio-grid')
    const coursewareGrid = document.querySelector('.courseware-generation-page .generation-grid')
    const process = studio?.querySelector('.process-panel') || coursewareGrid?.querySelector('.process-panel')
    const resources = studio?.querySelector('.resources-panel') || coursewareGrid?.querySelector('.details-panel')
    const processTitle = process?.querySelector('.panel-title')
    const resourcesTitle = resources?.querySelector('.panel-title')
    const processScroll = document.querySelector('.process-scroll')
    const resourceStage = document.querySelector('.resource-stage')
    const mainRegion = studio || coursewareGrid
    const selectorFields = [...document.querySelectorAll('.task-selector .selector-field')]
    const summaryItems = [...document.querySelectorAll('.job-summary .summary-item')]
    const status = document.querySelector('.job-summary .production-status')
    const textActions = document.querySelector('.resources-panel > .panel-title .task-actions')
    const coursewareActions = document.querySelector('.courseware-generation-page .details-panel > .panel-title .task-actions')
    const actionToolbar = textActions || coursewareActions
    const readerCard = document.querySelector('.resource-stage .reader-card')
    const readerHeader = readerCard?.querySelector('.reader-header')
    const resourceToolbar = document.querySelector('.resources-panel .resource-toolbar')
    const readerToolbarActions = resourceToolbar?.querySelector('.reader-toolbar-actions')
    const readerActionAnchor = resourceToolbar?.querySelector('#generation-reader-actions.reader-resource-actions')
    const readerTitle = readerCard?.querySelector('.resource-content h1')
    const resourceDifficulty = readerActionAnchor?.querySelector('.resource-difficulty')
    const downloadButton = readerActionAnchor?.querySelector('.download-button')
    const learningModeButton = readerToolbarActions?.querySelector('.learning-mode-action')
    const appendButton = document.querySelector('.resources-panel > .panel-title .task-actions .status-action-append')
    const selectors = ['.task-selector', '.job-summary', '.studio-grid', '.courseware-generation-page .generation-grid']
    return {
      viewport: { width: innerWidth, height: innerHeight },
      fit: Boolean(root?.classList.contains('is-fit-layout')),
      root: rect(root),
      rootScroll: root ? { top: root.scrollTop, width: root.scrollWidth, clientWidth: root.clientWidth, height: root.scrollHeight, clientHeight: root.clientHeight } : null,
      content: content ? { top: content.scrollTop, width: content.scrollWidth, clientWidth: content.clientWidth, height: content.scrollHeight, clientHeight: content.clientHeight } : null,
      document: { top: document.documentElement.scrollTop, width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, height: document.documentElement.scrollHeight, clientHeight: document.documentElement.clientHeight },
      sections: Object.fromEntries(selectors.map((selector) => [selector, rect(document.querySelector(selector))])),
      selectorFields: selectorFields.map(rect),
      summaryItems: summaryItems.map((node) => ({ ...rect(node), text: node.innerText.trim() })),
      summaryStatus: status ? { ...rect(status), text: status.innerText.trim(), role: status.getAttribute('role'), ariaLive: status.getAttribute('aria-live'), ariaAtomic: status.getAttribute('aria-atomic'), iconCount: status.querySelectorAll('svg').length } : null,
      actionToolbar: actionToolbar ? {
        ...rect(actionToolbar),
        heading: rect(actionToolbar.parentElement),
        buttons: [...actionToolbar.querySelectorAll('button')].map((node) => ({ ...rect(node), text: node.innerText.trim(), visible: node.getClientRects().length > 0 })),
      } : null,
      actionToolbarKind: textActions ? 'text' : coursewareActions ? 'courseware' : null,
      mainRegion: rect(mainRegion),
      studio: rect(studio),
      mainHeightShare: mainRegion && root?.clientHeight ? mainRegion.getBoundingClientRect().height / root.clientHeight : null,
      process: rect(process),
      resources: rect(resources),
      reader: readerCard ? {
        card: rect(readerCard),
        headerCount: readerCard.querySelectorAll('.reader-header').length,
        difficultyCount: resourceToolbar?.querySelectorAll('.reader-resource-actions .resource-difficulty').length || 0,
        downloadCount: resourceToolbar?.querySelectorAll('.reader-resource-actions .download-button').length || 0,
        learningModeCount: resourceToolbar?.querySelectorAll('.learning-mode-action').length || 0,
        toolbar: resourceToolbar ? { ...rect(resourceToolbar), scrollWidth: resourceToolbar.scrollWidth, clientWidth: resourceToolbar.clientWidth } : null,
        toolbarActions: readerToolbarActions ? rect(readerToolbarActions) : null,
        learningModeLast: readerToolbarActions?.lastElementChild?.classList.contains('learning-mode-action') || false,
        actionAnchor: readerActionAnchor ? { ...rect(readerActionAnchor), role: readerActionAnchor.getAttribute('role'), ariaLabel: readerActionAnchor.getAttribute('aria-label') } : null,
        title: readerTitle ? { ...rect(readerTitle), text: readerTitle.innerText.trim(), whiteSpace: getComputedStyle(readerTitle).whiteSpace, textOverflow: getComputedStyle(readerTitle).textOverflow, overflowX: getComputedStyle(readerTitle).overflowX, overflowY: getComputedStyle(readerTitle).overflowY, scrollWidth: readerTitle.scrollWidth, clientWidth: readerTitle.clientWidth } : null,
        difficulty: resourceDifficulty ? { ...rect(resourceDifficulty), text: resourceDifficulty.innerText.trim(), visible: resourceDifficulty.getClientRects().length > 0 } : null,
        download: downloadButton ? { ...rect(downloadButton), text: downloadButton.innerText.trim(), visible: downloadButton.getClientRects().length > 0 } : null,
        learningMode: learningModeButton ? { ...rect(learningModeButton), text: learningModeButton.innerText.trim(), visible: learningModeButton.getClientRects().length > 0 } : null,
        append: appendButton ? rect(appendButton) : null,
      } : null,
      headings: { process: rect(processTitle), resources: rect(resourcesTitle) },
      processScroll: processScroll ? { top: processScroll.scrollTop, height: processScroll.scrollHeight, clientHeight: processScroll.clientHeight, width: processScroll.scrollWidth, clientWidth: processScroll.clientWidth } : null,
      resourceStage: resourceStage ? { top: resourceStage.scrollTop, height: resourceStage.scrollHeight, clientHeight: resourceStage.clientHeight, width: resourceStage.scrollWidth, clientWidth: resourceStage.clientWidth } : null,
      externalOverflow: [...document.querySelectorAll('.generate-page *')].filter((node) => {
        const r = node.getBoundingClientRect()
        return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1)
      }).slice(0, 12).map((node) => ({
        selector: node.className?.baseVal || node.className || node.tagName,
        tag: node.tagName,
        text: node.textContent.trim().slice(0, 100),
        parent: node.parentElement?.className?.baseVal || node.parentElement?.className || node.parentElement?.tagName || '',
        grandparent: node.parentElement?.parentElement?.className?.baseVal || node.parentElement?.parentElement?.className || node.parentElement?.parentElement?.tagName || '',
        left: node.getBoundingClientRect().left,
        right: node.getBoundingClientRect().right,
      })),
    }
  })
  assert.ok(metrics.root, label + ': missing generation root')
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, label + ': document horizontal overflow')
  assert.ok(metrics.rootScroll.width <= metrics.rootScroll.clientWidth + 1, label + ': generation root horizontal overflow')
  assert.ok(metrics.content.width <= metrics.content.clientWidth + 1, label + ': app content horizontal overflow')
  assert.equal(metrics.document.top, 0, label + ': document must start at scrollTop 0')
  assert.equal(metrics.rootScroll.top, 0, label + ': generation root must start at scrollTop 0')
  assert.equal(metrics.content.top, 0, label + ': outer app content must start at scrollTop 0')
  if (requireFit) {
    assert.equal(metrics.fit, true, label + ': measured desktop should enable fit layout')
    assert.ok(metrics.document.height <= metrics.document.clientHeight + 1, label + ': fit layout should prevent document scrolling')
    assert.ok(metrics.rootScroll.height <= metrics.rootScroll.clientHeight + 1, label + ': fit layout should contain generation content')
    assert.ok(Math.abs(metrics.headings.process.top - metrics.headings.resources.top) <= 1, label + ': process/resource headings should align')
    for (const [selector, rect] of Object.entries(metrics.sections)) {
      if (!rect) continue
      assert.ok(rect.top >= metrics.root.top - 1 && rect.bottom <= metrics.root.bottom + 1, label + ': section is clipped in fit layout: ' + selector)
    }
    assert.ok(metrics.processScroll.clientHeight >= 120, label + ': process reading region should retain usable height')
    assert.ok(metrics.resourceStage.clientHeight >= 120, label + ': resource reading region should retain usable height')
  }
  if (metrics.viewport.width >= 1100) {
    assert.equal(metrics.selectorFields.length, 2, label + ': profile and batch selectors should form two side-by-side fields')
    assert.ok(Math.abs(metrics.selectorFields[0].top - metrics.selectorFields[1].top) <= 1, label + ': selector fields should stay on one horizontal row')
    assert.ok(Math.abs(metrics.selectorFields[0].bottom - metrics.selectorFields[1].bottom) <= 1, label + ': selector fields should have aligned row bottoms')
    assert.ok(metrics.selectorFields[0].right <= metrics.selectorFields[1].left + 1, label + ': selector fields should occupy distinct adjacent columns')
    assert.ok(metrics.sections['.task-selector'].width >= metrics.root.width * 0.95, label + ': selector row should use the full control width')
    assert.ok(metrics.selectorFields[0].width + metrics.selectorFields[1].width >= metrics.sections['.task-selector'].width * 0.8, label + ': selector columns should fill the control row')
    assert.equal(metrics.summaryItems.length, 6, label + ': job summary should show all six facts')
    const summaryOrder = ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']
    const summaryTop = metrics.summaryItems[0].top
    const summaryBottom = metrics.summaryItems[0].bottom
    for (let index = 0; index < metrics.summaryItems.length; index += 1) {
      const item = metrics.summaryItems[index]
      assert.ok(item.text.includes(summaryOrder[index]), label + ': job summary fact order changed at index ' + index + ': ' + JSON.stringify(item))
      assert.ok(Math.abs(item.top - summaryTop) <= 1 && Math.abs(item.bottom - summaryBottom) <= 1, label + ': all six summary cells should share one full row: ' + JSON.stringify(item))
      if (index > 0) assert.ok(metrics.summaryItems[index - 1].right <= item.left + 1, label + ': summary cells should occupy separate columns')
    }
    assert.ok(metrics.sections['.job-summary'].width >= metrics.root.width * 0.95, label + ': six-fact summary should span the full page row')
    assert.ok(metrics.summaryStatus, label + ': task state should be included in the summary row')
    assert.equal(metrics.summaryStatus.role, 'status', label + ': moved production state should retain status semantics')
    assert.equal(metrics.summaryStatus.ariaLive, 'polite', label + ': moved production state should retain its live announcement')
    assert.equal(metrics.summaryStatus.ariaAtomic, 'true', label + ': moved production state should remain atomic')
    assert.ok(metrics.summaryStatus.iconCount > 0, label + ': task state should retain its semantic icon')
    assert.equal(await page.locator('.status-actions').count(), 0, label + ': deleted top-level action row should not return')
    assert.ok(metrics.actionToolbar, label + ': task actions should move into the panel title')
    assert.ok(metrics.actionToolbar.width > 0, label + ': local action toolbar should remain visible')
    assert.ok(metrics.actionToolbar.left >= metrics.actionToolbar.heading.left - 1 && metrics.actionToolbar.right <= metrics.actionToolbar.heading.right + 1, label + ': local toolbar should remain inside its panel heading')
    for (const button of metrics.actionToolbar.buttons) {
      assert.ok(button.visible && button.left >= metrics.actionToolbar.left - 1 && button.right <= metrics.actionToolbar.right + 1, label + ': local action should remain visible inside its toolbar: ' + JSON.stringify(button))
      assert.ok(button.height >= 44, label + ': local task action should meet the 44px target: ' + JSON.stringify(button))
    }
    for (let index = 1; index < metrics.actionToolbar.buttons.length; index += 1) {
      const previous = metrics.actionToolbar.buttons[index - 1]
      const current = metrics.actionToolbar.buttons[index]
      const overlapX = previous.left < current.right && current.left < previous.right
      const overlapY = previous.top < current.bottom && current.top < previous.bottom
      assert.ok(!(overlapX && overlapY), label + ': local task action buttons should not overlap')
    }
  }
  if (metrics.viewport.width >= 1280 && metrics.studio) {
    assert.ok(metrics.process.width >= 280, label + ': text process column should remain at least 280px wide')
    assert.ok(metrics.process.width <= metrics.root.width * 0.34, label + ': text process column should stay within roughly one third of the page')
    assert.ok(metrics.resources.width > metrics.process.width && metrics.resources.width >= metrics.studio.width * 0.6, label + ': text resource preview should receive the wider column')
  }
  if (metrics.viewport.width >= 1280 && metrics.sections['.courseware-generation-page .generation-grid']) {
    assert.ok(metrics.process.width > metrics.mainRegion.width * 0.34 && metrics.process.width < metrics.mainRegion.width * 0.5, label + ': embedded courseware should keep its original two-column balance')
    assert.ok(metrics.resources.width > metrics.process.width, label + ': courseware details should remain the wider column')
  }
  if (metrics.viewport.width >= 1280 && metrics.viewport.height >= 800 && metrics.studio && metrics.mainHeightShare != null) {
    assert.ok(metrics.mainHeightShare >= 0.66, label + ': normal text work area should occupy at least 66% of available root height: ' + JSON.stringify({ mainHeightShare: metrics.mainHeightShare, mainRegion: metrics.mainRegion, root: metrics.root }))
  }
  if (metrics.reader) {
    assert.equal(metrics.reader.headerCount, 0, label + ': generation reader header should be removed')
    assert.ok(metrics.reader.toolbar && metrics.reader.toolbarActions && metrics.reader.actionAnchor, label + ': reader actions should be merged into the resource toolbar')
    assert.equal(metrics.reader.learningModeLast, true, label + ': learning mode should be the final toolbar action')
    assert.equal(metrics.reader.actionAnchor.role, 'group', label + ': teleported grade/download controls should retain a named group')
    assert.equal(metrics.reader.actionAnchor.ariaLabel, '资源文件操作', label + ': teleported grade/download group should be accessible')
    assert.equal(metrics.reader.difficultyCount, 1, label + ': generation reader should show one difficulty control in its toolbar')
    assert.equal(metrics.reader.downloadCount, 1, label + ': generation reader should show one download control in its toolbar')
    assert.equal(metrics.reader.learningModeCount, 1, label + ': generation reader should show one learning mode action in its toolbar')
    assert.ok(metrics.reader.toolbar.scrollWidth <= metrics.reader.toolbar.clientWidth + 1, label + ': merged resource toolbar should not overflow horizontally')
    assert.ok(metrics.reader.difficulty?.visible, label + ': difficulty should remain visible in the resource toolbar')
    assert.ok(metrics.reader.download?.visible, label + ': fixture file path should expose download in the resource toolbar')
    assert.equal(metrics.reader.download.text, '下载材料', label + ': download control should retain its action label')
    assert.ok(metrics.reader.learningMode?.visible, label + ': learning mode should remain visible in the resource toolbar')
    assert.equal(metrics.reader.learningMode.text, '学习模式', label + ': learning mode action should use its compact label')
    for (const control of [metrics.reader.difficulty, metrics.reader.download, metrics.reader.learningMode]) {
      assert.ok(control.left >= metrics.reader.toolbar.left - 1 && control.right <= metrics.reader.toolbar.right + 1, label + ': reader control should remain inside the resource toolbar: ' + JSON.stringify(control))
    }
    for (const control of [metrics.reader.difficulty, metrics.reader.download]) {
      assert.ok(control.left >= metrics.reader.actionAnchor.left - 1 && control.right <= metrics.reader.actionAnchor.right + 1, label + ': teleported reader controls should remain in their resource action group: ' + JSON.stringify(control))
    }
    assert.ok(metrics.reader.download.height >= 44, label + ': download control should meet the 44px target')
    assert.ok(metrics.reader.learningMode.height >= 44, label + ': learning mode control should meet the 44px target')
    const controls = [metrics.reader.difficulty, metrics.reader.download, metrics.reader.learningMode]
    for (let index = 0; index < controls.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < controls.length; otherIndex += 1) {
        const left = controls[index]
        const right = controls[otherIndex]
        const overlapX = left.left < right.right && right.left < left.right
        const overlapY = left.top < right.bottom && right.top < left.bottom
        assert.ok(!(overlapX && overlapY), label + ': reader toolbar controls should not overlap')
      }
    }
    if (metrics.reader.title?.text.includes('多阶段知识迁移')) {
      assert.ok(metrics.reader.title.text.includes('节点A、节点B'), label + ': long resource type title should retain the complete resource identity')
      assert.equal(metrics.reader.title.whiteSpace, 'normal', label + ': long resource title should wrap in the resource body')
      assert.ok(!['hidden', 'clip'].includes(metrics.reader.title.overflowX) && !['hidden', 'clip'].includes(metrics.reader.title.overflowY), label + ': full resource title should not be clipped')
      if (metrics.reader.title.clientWidth > 0) assert.ok(metrics.reader.title.scrollWidth <= metrics.reader.title.clientWidth + 1, label + ': complete body title should fit its visible box')
    }
    if (metrics.viewport.width >= 1280) {
      assert.ok(metrics.reader.append, label + ': append action should remain available above the reading toolbar')
      assert.ok(Math.abs(metrics.reader.append.width - 112) <= 1, label + ': append action should retain its 112px target width')
      assert.ok(Math.abs(metrics.reader.learningMode.width - metrics.reader.append.width) <= 1, label + ': learning mode and append actions should have equal widths')
      assert.ok(Math.abs(metrics.reader.learningMode.right - metrics.reader.append.right) <= 1, label + ': learning mode and append actions should share a right edge')
    }
  }
  if (metrics.processScroll) assert.ok(metrics.processScroll.width <= metrics.processScroll.clientWidth + 1, label + ': process region horizontal overflow')
  if (metrics.resourceStage) assert.ok(metrics.resourceStage.width <= metrics.resourceStage.clientWidth + 1, label + ': resource region horizontal overflow')
  evidence.layoutChecks.push({ label, ...metrics })
  return metrics
}

async function assertSummaryAndActions(page, label) {
  const statusLocator = page.locator('.job-summary .production-status')
  const status = await statusLocator.innerText()
  const summary = await page.locator('.job-summary').innerText()
  for (const semantic of ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']) {
    assert.ok(summary.includes(semantic), label + ': missing job summary fact ' + semantic)
  }
  assert.ok(summary.includes('AI 应用开发'), label + ': summary should show the selected learning direction')
  assert.ok(status.includes('已完成'), label + ': production status should show the terminal task state')
  assert.equal(await statusLocator.getAttribute('role'), 'status', label + ': production state should retain status semantics')
  assert.equal(await statusLocator.getAttribute('aria-live'), 'polite', label + ': production state should retain its live announcement')
  assert.ok(await statusLocator.locator('svg').count(), label + ': production state icon should remain visible')
  assert.equal(await page.locator('.production-intro, .production-banner, .production-context').count(), 0, label + ': top-level intro and banner should be removed')
  await assertNoLocalHistoryAction(page, label)
  const localActions = page.locator('.resources-panel > .panel-title .task-actions')
  assert.equal(await localActions.count(), 1, label + ': task actions should live in the resource panel heading')
  assert.ok(await localActions.getByRole('button', { name: '刷新资源', exact: true }).count(), label + ': resource refresh should keep its full label')
  assert.ok(await localActions.getByRole('button', { name: '追加资源', exact: false }).count(), label + ': append action should remain in the resource panel heading')
  assert.equal(await page.getByRole('combobox', { name: '学习画像' }).count(), 1, label + ': profile selector needs an accessible name')
  assert.equal(await page.getByRole('combobox', { name: '资源批次' }).count(), 1, label + ': batch selector needs an accessible name')
  const targets = await page.evaluate(() => [...document.querySelectorAll(
    '.task-actions button, .learning-mode-action, .primary-action',
  )].filter((node) => {
    const rect = node.getBoundingClientRect()
    return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden'
  }).map((node) => ({ text: node.innerText.trim(), height: node.getBoundingClientRect().height })))
  for (const target of targets) {
    assert.ok(target.height >= 44, label + ': primary action is shorter than 44px ' + JSON.stringify(target))
  }
  evidence.interactionChecks.push({ label, summaryFacts: 6, namedSelectors: 2, primaryTargets: targets })
}

async function assertNoLocalHistoryAction(page, label) {
  assert.equal(await page.locator('.status-actions').count(), 0, label + ': old top-level task action row should be removed')
  assert.equal(await page.locator('.status-action-history').count(), 0, label + ': duplicate local learning history action should be removed')
  assert.equal(await page.getByRole('button', { name: '查看学习历史', exact: true }).count(), 0, label + ': local history button should not be duplicated')
  assert.equal(await page.getByRole('button', { name: '学习历史', exact: true }).count(), 1, label + ': topbar learning history route should remain')
}

async function assertResourcePhases(page, label, { longMetadata = false } = {}) {
  const metrics = await page.locator('.resource-progress-tree').evaluate((tree) => {
    const phases = [...tree.querySelectorAll('.resource-phase')]
    const headings = phases.map((phase) => phase.querySelector('.el-collapse-item__header'))
    const order = [...tree.querySelectorAll('.phase-order')]
    const line = getComputedStyle(tree, '::before')
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    return {
      phases: phases.map((phase, index) => ({
        className: phase.className,
        active: phase.classList.contains('is-active'),
        heading: rect(headings[index]),
        label: phase.querySelector('.phase-name')?.textContent.trim() || '',
      })),
      order: order.map((node) => ({ text: node.textContent.trim(), ...rect(node) })),
      connector: {
        content: line.content,
        top: Number.parseFloat(line.top),
        bottom: Number.parseFloat(line.bottom),
        width: Number.parseFloat(line.width),
        height: tree.clientHeight - Number.parseFloat(line.top) - Number.parseFloat(line.bottom),
        backgroundColor: line.backgroundColor,
      },
      cards: [...tree.querySelectorAll('.execution-card')].map((node) => ({
        className: node.className,
        phase: node.closest('.resource-phase')?.querySelector('.phase-name')?.textContent.trim() || '',
      })),
      metadata: [...tree.querySelectorAll('.execution-meta')].map((node) => ({
        text: node.innerText.trim(),
        flexWrap: getComputedStyle(node).flexWrap,
        width: node.clientWidth,
        scrollWidth: node.scrollWidth,
        spans: [...node.querySelectorAll(':scope > span')].map((span) => ({
          text: span.innerText.trim(),
          width: span.clientWidth,
          scrollWidth: span.scrollWidth,
          whiteSpace: getComputedStyle(span).whiteSpace,
          textOverflow: getComputedStyle(span).textOverflow,
          overflowX: getComputedStyle(span).overflowX,
        })),
      })),
    }
  })
  assert.equal(metrics.phases.length, 2, label + ': resource workflow should retain its two phases')
  assert.deepEqual(metrics.phases.map((phase) => phase.label), ['资源生成', '审核与发布'], label + ': resource phases should keep their original order')
  assert.ok(metrics.phases.every((phase) => phase.active), label + ': both resource phases should remain expanded and readable')
  assert.deepEqual(metrics.order.map((item) => item.text), ['01', '02'], label + ': phase numbers should be present in order')
  assert.ok(Math.abs((metrics.order[0].top + metrics.order[0].bottom) / 2 - (metrics.phases[0].heading.top + metrics.phases[0].heading.bottom) / 2) <= 1, label + ': first phase marker should align with its heading')
  assert.ok(Math.abs((metrics.order[1].top + metrics.order[1].bottom) / 2 - (metrics.phases[1].heading.top + metrics.phases[1].heading.bottom) / 2) <= 1, label + ': second phase marker should align with its heading')
  assert.ok(metrics.order[0].top < metrics.order[1].top, label + ': numbered phase markers should follow the vertical flow')
  assert.notEqual(metrics.connector.content, 'none', label + ': phase connector should be rendered')
  assert.ok(metrics.connector.width >= 1 && metrics.connector.height > 0, label + ': phase connector should have visible geometry')
  assert.notEqual(metrics.connector.backgroundColor, 'rgba(0, 0, 0, 0)', label + ': phase connector should have a visible line color')
  assert.ok(metrics.cards.length >= 3, label + ': generation/review cards should remain available')
  assert.ok(metrics.cards.every((card) => /\bis-(success|warning|danger|info)\b/.test(card.className)), label + ': resource cards should expose their phase status style class')
  for (const metadata of metrics.metadata) {
    assert.equal(metadata.flexWrap, 'wrap', label + ': execution metadata should wrap instead of clipping')
    assert.ok(metadata.scrollWidth <= metadata.width + 1, label + ': execution metadata row should not overflow horizontally')
    for (const span of metadata.spans) {
      assert.ok(span.scrollWidth <= span.width + 1, label + ': execution metadata should remain fully readable: ' + JSON.stringify(span))
      assert.equal(span.textOverflow, 'clip', label + ': execution metadata should not be ellipsized: ' + JSON.stringify(span))
      assert.ok(!['hidden', 'clip'].includes(span.overflowX), label + ': execution metadata should not be clipped: ' + JSON.stringify(span))
    }
  }
  if (longMetadata) {
    const longRow = metrics.metadata.find((item) => item.text.includes('资源生成与跨阶段证据核验协作 Agent'))
    assert.ok(longRow, label + ': long fixture should render its expanded execution metadata')
    assert.ok(longRow.text.includes('来源快照与发布范围一致性及学习目标覆盖校验通过'), label + ': long fixture should retain its validation metadata')
    assert.ok(longRow.spans.length >= 5, label + ': long fixture should preserve each execution metadata field')
  }
  evidence.layoutChecks.push({ label: label + '-resource-phases', ...metrics })
}

async function capture(page, filename) {
  const pathName = path.join(reportDir, filename + '.png')
  await page.screenshot({ path: pathName, animations: 'disabled' })
  evidence.screenshots.push({ filename: path.basename(pathName), path: pathName, viewport: page.viewportSize() })
}

async function assertNoExternalOrUnexpected(label) {
  assert.deepEqual(externalRequests, [], label + ': browser requested an external origin')
  assert.deepEqual(state.unexpectedApi, [], label + ': fixture saw an unmocked API call')
  assert.deepEqual(browserErrors, [], label + ': pageerror was reported')
}

async function assertContrast(page, label) {
  const checks = await page.evaluate(() => {
  const selectors = [
      '.job-summary .production-status', '.job-summary .production-status strong',
      '.job-summary .summary-item span', '.job-summary .summary-item strong',
      '.studio-grid .panel-title h3', '.process-scroll', '.resource-stage', '.execution-card strong',
      '.process-scroll .el-tag__content', '.resource-toolbar .resource-difficulty', '.resource-toolbar .download-button',
      '.execution-card-head .el-tag__content', '.execution-objective', '.execution-meta',
      '.resource-content h2', '.resource-content p',
      '.el-dialog__title', '.source-hint', '.source-list .el-checkbox__label', '.source-list span',
      '.el-dialog__footer button', '.courseware-generation-page .scene-list strong',
      '.courseware-generation-page .scene-list small', '.courseware-generation-page .warnings',
      '.courseware-generation-page .scene-list button', '.courseware-generation-page .process-actions button',
      '.task-actions button', '.learning-mode-action',
      '.library-empty .library-preparation-actions .el-button--primary',
      '.resources-page .learning-toolbar .field-label', '.resources-page .toolbar-actions button',
      '.resources-page .resource-feedback-button', '.resources-page .resource-item.is-active strong',
      '.resources-page .resource-item.is-active small', '.resources-page .resource-item strong',
      '.resources-page .resource-item small', '.resources-page .focus-resource-switcher button.is-active strong',
      '.resources-page .focus-resource-switcher button.is-active small', '.resources-page .focus-exit',
      '.resources-page .tutor-trigger', '.resources-page .reader-header .download-button',
      '.resources-page .resource-content h1', '.resources-page .resource-content h2',
      '.resources-page .resource-content p',
    ]
    const parseColor = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/i)
      if (!match) return null
      const values = match[1].split(',').map((part) => Number.parseFloat(part.trim()))
      return { rgb: values.slice(0, 3), alpha: values.length > 3 ? values[3] : 1 }
    }
    const blend = (top, bottom) => {
      const alpha = top.alpha
      return top.rgb.map((value, index) => value * alpha + bottom[index] * (1 - alpha))
    }
    const luminance = (rgb) => {
      const channels = rgb.map((value) => {
        const v = value / 255
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const contrast = (a, b) => {
      const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }
    const results = []
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const style = getComputedStyle(node)
        const text = node.textContent.trim() || node.getAttribute('aria-label') || node.getAttribute('title') || ''
        if (!node.getClientRects().length || !text) continue
        const foreground = parseColor(style.color)
        if (!foreground) continue
        let backgrounds = [[255, 255, 255]]
        const chain = []
        let current = node
        while (current && current !== document.documentElement) {
          chain.push(current)
          current = current.parentElement
        }
        for (current of chain.reverse()) {
          const computed = getComputedStyle(current)
          const imageColors = computed.backgroundImage === 'none'
            ? []
            : [...computed.backgroundImage.matchAll(/rgba?\([^)]+\)/gi)].map((match) => parseColor(match[0])).filter(Boolean)
          if (imageColors.length) {
            const underlying = backgrounds
            backgrounds = imageColors.flatMap((color) => underlying.map((bg) => blend(color, bg)))
          }
          const color = parseColor(computed.backgroundColor)
          if (color && color.alpha > 0) backgrounds = backgrounds.map((bg) => blend(color, bg))
        }
        const composedForeground = foreground.alpha < 1 ? blend(foreground, backgrounds[0]) : foreground.rgb
        const ratios = backgrounds.map((background) => contrast(composedForeground, background))
        results.push({ selector, text: text.slice(0, 70), color: style.color, backgrounds, contrast: Math.min(...ratios) })
      }
    }
    return results
  })
  assert.ok(checks.length > 0, label + ': no visible contrast samples were collected')
  for (const check of checks) {
    assert.ok(check.contrast >= 4.5, label + ': contrast below 4.5:1 for ' + check.selector + ' ' + JSON.stringify(check))
  }
  evidence.contrastChecks.push({ label, checks })
}

async function resourcesCardColorSnapshot(page, label) {
  const snapshot = await page.evaluate((name) => {
    const card = document.querySelector('.resources-page .resource-item.is-active')
    const strong = card?.querySelector('strong')
    const small = card?.querySelector('small')
    const cardStyle = card ? getComputedStyle(card) : null
    const textStyle = strong ? getComputedStyle(strong) : null
    const detailStyle = small ? getComputedStyle(small) : null
    return {
      label: name,
      cardText: card?.innerText.trim() || '',
      foreground: textStyle?.color || null,
      detailForeground: detailStyle?.color || null,
      backgroundColor: cardStyle?.backgroundColor || null,
      backgroundImage: cardStyle?.backgroundImage || null,
      transitionProperty: cardStyle?.transitionProperty || null,
      transitionDuration: cardStyle?.transitionDuration || null,
    }
  }, label)
  evidence.resourcesStyleSnapshots ||= []
  evidence.resourcesStyleSnapshots.push(snapshot)
  return snapshot
}

async function assertResourcesCardContrast(page, label) {
  const immediate = await resourcesCardColorSnapshot(page, label + '-immediate')
  try {
    await assertContrast(page, label)
  } catch (error) {
    await page.waitForTimeout(300)
    const settled = await resourcesCardColorSnapshot(page, label + '-after-300ms')
    error.message += '\nResources card computed style diagnostic: ' + JSON.stringify({ immediate, settled })
    throw error
  }
  return immediate
}

async function assertInternalScroll(page, label) {
  const regions = ['.process-scroll', '.resource-stage']
  for (const selector of regions) {
    const locator = page.locator(selector)
    assert.equal(await locator.count(), 1, label + ': expected exactly one scroll region ' + selector)
    const expectedLabel = selector === '.process-scroll' ? '生成协作轨迹' : '学习资源预览'
    assert.equal(await locator.getAttribute('aria-label'), expectedLabel, label + ': scroll region accessible name changed')
    assert.equal(await locator.getAttribute('tabindex'), '0', label + ': scroll region should be keyboard focusable')
    const before = await locator.evaluate((node) => ({ top: node.scrollTop, max: node.scrollHeight - node.clientHeight, height: node.clientHeight }))
    assert.ok(before.max > 0, label + ': long fixture should create scrollable content in ' + selector)
    await locator.evaluate((node) => { node.scrollTop = Math.min(140, node.scrollHeight) })
    await page.waitForTimeout(60)
    const afterProgram = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterProgram > before.top, label + ': programmatic scroll should move ' + selector)
    await locator.evaluate((node) => { node.scrollTop = 0 })
    const box = await locator.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 260)
    await page.waitForTimeout(60)
    const afterWheel = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterWheel > 0, label + ': wheel should scroll ' + selector)
    await locator.evaluate((node) => { node.scrollTop = 0; node.focus() })
    await page.keyboard.press('PageDown')
    await page.waitForTimeout(60)
    const afterKeyboard = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterKeyboard > 0, label + ': PageDown should scroll ' + selector)
    const focusVisible = await locator.evaluate((node) => ({
      active: document.activeElement === node,
      focusVisible: node.matches(':focus-visible'),
      outlineStyle: getComputedStyle(node).outlineStyle,
      outlineWidth: getComputedStyle(node).outlineWidth,
      boxShadow: getComputedStyle(node).boxShadow,
    }))
    assert.equal(focusVisible.active, true, label + ': scroll region should be keyboard focusable')
    assert.ok(focusVisible.focusVisible || focusVisible.outlineStyle !== 'none' || focusVisible.boxShadow !== 'none', label + ': scroll region focus indicator is not visible')
    evidence.scrollChecks.push({ label, selector, before, afterProgram, afterWheel, afterKeyboard, focusVisible })
  }
  const outerBefore = await page.evaluate(() => ({
    document: document.documentElement.scrollTop,
    content: document.querySelector('.content-area')?.scrollTop ?? null,
    root: document.querySelector('.generate-page')?.scrollTop ?? null,
  }))
  for (const selector of regions) {
    const locator = page.locator(selector)
    await locator.evaluate((node) => { node.scrollTop = node.scrollHeight })
    const box = await locator.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 700)
    await page.waitForTimeout(80)
    const outerAfter = await page.evaluate(() => ({
      document: document.documentElement.scrollTop,
      content: document.querySelector('.content-area')?.scrollTop ?? null,
      root: document.querySelector('.generate-page')?.scrollTop ?? null,
    }))
    assert.deepEqual(outerAfter, outerBefore, label + ': edge wheel must stay inside ' + selector)
    evidence.scrollChecks.push({ label, kind: 'edge-containment', selector, outerBefore, outerAfter })
  }
}

async function waitForFixture(predicate, label, timeoutMs = 7000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(label + ': fixture condition timed out')
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}

async function chooseOption(page, name, optionName) {
  const input = page.getByRole('combobox', { name })
  const shell = input.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]')
  await assertWrappedFieldFocus(page, `generation-${name}`, input, shell)
  await input.click()
  await page.getByRole('option', { name: optionName }).click()
}

async function assertWrappedFieldFocus(page, label, control, shell, screenshotName = null, { singleBorderControl = false, keyboardFocus = true } = {}) {
  const baseline = await shell.evaluate((node) => {
    const style = getComputedStyle(node)
    return { borderColor: style.borderTopColor, borderWidth: style.borderTopWidth, boxShadow: style.boxShadow }
  })
  await control.click()
  await page.waitForTimeout(240)
  const shellHandle = await shell.elementHandle()
  const controlHandle = await control.elementHandle()
  const focused = await page.evaluate(({ shell, control }) => {
    const outer = getComputedStyle(shell)
    const inner = getComputedStyle(control)
    return {
      active: document.activeElement === control,
      focusWithin: shell.matches(':focus-within'),
      hovered: shell.matches(':hover'),
      shell: { outlineStyle: outer.outlineStyle, outlineWidth: outer.outlineWidth, borderColor: outer.borderTopColor, borderWidth: outer.borderTopWidth, boxShadow: outer.boxShadow },
      control: {
        outlineStyle: inner.outlineStyle, outlineWidth: inner.outlineWidth,
        borderWidths: ['Top', 'Right', 'Bottom', 'Left'].map((side) => Number.parseFloat(inner['border' + side + 'Width']) || 0),
      },
    }
  }, { shell: shellHandle, control: controlHandle })
  if (screenshotName) await capture(page, screenshotName)
  const details = JSON.stringify({ baseline, focused })
  assert.equal(focused.active, true, label + ': click should focus the inner control: ' + details)
  assert.equal(focused.focusWithin, true, label + ': outer shell should retain focus-within: ' + details)
  assert.equal(focused.hovered, true, label + ': focus sample should retain hover: ' + details)
  assert.ok(focused.control.outlineStyle === 'none' || Number.parseFloat(focused.control.outlineWidth) === 0,
    label + ': inner control should not draw a separate outline: ' + details)
  assert.ok(focused.shell.outlineStyle === 'none' || Number.parseFloat(focused.shell.outlineWidth) === 0,
    label + ': wrapper should use its focus shadow/border without a second outline: ' + details)
  if (!singleBorderControl) assert.ok(focused.control.borderWidths.every((width) => width <= 0.5),
    label + ': inner input should not draw a second border: ' + details)
  const shadowVisible = focused.shell.boxShadow !== 'none'
    && focused.shell.boxShadow !== baseline.boxShadow
    && !/rgba\([^)]*,\s*0(?:\.0+)?\)/i.test(focused.shell.boxShadow)
  const borderVisible = focused.shell.borderColor !== baseline.borderColor && Number.parseFloat(focused.shell.borderWidth) > 0
  assert.ok(shadowVisible || borderVisible,
    label + ': focused wrapper should show a clear border or shadow while hovered: ' + details)
  evidence.interactionChecks.push({ scenario: 'wrapped-field-focus', label, baseline, focused })
  if (keyboardFocus) {
    await page.keyboard.press('Escape')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    const keyboard = await control.evaluate((node) => ({ active: document.activeElement === node, focusVisible: node.matches(':focus-visible') }))
    assert.equal(keyboard.active, true, label + ': keyboard tab navigation should return to the control: ' + JSON.stringify(keyboard))
    assert.equal(keyboard.focusVisible, true, label + ': keyboard focus should remain visible: ' + JSON.stringify(keyboard))
    evidence.interactionChecks.push({ scenario: 'wrapped-field-keyboard-focus', label, keyboard })
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
  assert.ok(selectedText.includes(expectedText), label + ': keyboard selection should choose ' + expectedText + '; got ' + selectedText)
  evidence.interactionChecks.push({ scenario: 'filterable-select-keyboard', label, selectedText })
}

async function openAppendDialog(page, command) {
  await page.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: '追加资源', exact: false }).click()
  await page.getByRole('menuitem', { name: command, exact: true }).click()
  if (command === '文本学习资源') await page.getByRole('heading', { name: '追加学习资源' }).waitFor()
  else await page.getByRole('heading', { name: '创建互动课件' }).waitFor()
}

async function appendTextTypes(page, claimEnabled, keepTypes, screenshotName = null) {
  await openAppendDialog(page, '文本学习资源')
  if (!evidence.interactionChecks.some((item) => item.scenario === 'append-checkbox-keyboard-focus')) {
    const keyboardOption = page.locator('.append-resource-options input:not(:disabled)').first()
    assert.ok(await keyboardOption.count(), 'append resource checkbox should be enabled in the fixture')
    let reachedCheckbox = false
    for (let index = 0; index < 24; index += 1) {
      if (await keyboardOption.evaluate((input) => document.activeElement === input)) {
        reachedCheckbox = true
        break
      }
      await page.keyboard.press('Tab')
    }
    assert.equal(reachedCheckbox || await keyboardOption.evaluate((input) => document.activeElement === input), true,
      'Tab navigation should reach an append resource checkbox')
    const focusCue = await keyboardOption.evaluate((input) => {
      const shell = input.closest('.el-checkbox__input')
      const mark = shell?.querySelector('.el-checkbox__inner')
      const style = mark ? getComputedStyle(mark) : null
      return { active: document.activeElement === input, checked: input.checked, focusVisible: input.matches(':focus-visible'), focusClass: shell?.classList.contains('is-focus'), borderColor: style?.borderTopColor, boxShadow: style?.boxShadow }
    })
    assert.equal(focusCue.active, true, 'append resource checkbox should receive keyboard focus')
    assert.equal(focusCue.focusVisible, true, 'append resource checkbox should show :focus-visible')
    evidence.interactionChecks.push({ scenario: 'append-checkbox-keyboard-focus', focusCue })
  }
  const claim = page.locator('.append-claim-option .el-checkbox')
  const current = await claim.getAttribute('aria-checked')
  const checked = current === 'true' || await claim.locator('input').isChecked().catch(() => false)
  if (checked !== claimEnabled) await claim.click()
  const options = page.locator('.append-resource-options .el-checkbox')
  const count = await options.count()
  for (let index = 0; index < count; index += 1) {
    const option = options.nth(index)
    const text = (await option.innerText()).trim()
    const desired = keepTypes.some((type) => text.includes(type))
    const input = option.locator('input')
    const isChecked = await input.isChecked().catch(async () => option.getAttribute('aria-checked').then((value) => value === 'true'))
    if (isChecked !== desired) await option.click()
  }
  if (screenshotName) await capture(page, screenshotName)
  await page.getByRole('button', { name: '开始追加' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/continuations')), 'append request')
}

async function assertRouteFixtureReady(page, expectedPath) {
  await page.waitForFunction((pathName) => location.pathname === pathName, expectedPath)
  await page.waitForTimeout(100)
}

async function setResourcesSidebar(page, collapsed) {
  const shell = page.locator('.app-shell')
  const current = await shell.evaluate((node) => node.classList.contains('is-sidebar-collapsed'))
  if (current !== collapsed) {
    await page.locator('.sidebar-toggle').click()
    await page.waitForFunction((expected) => {
      const node = document.querySelector('.app-shell')
      return node?.classList.contains('is-sidebar-collapsed') === expected
        && !node.classList.contains('is-sidebar-animating')
    }, collapsed)
  }
  await page.waitForTimeout(40)
}

async function assertResourcesGeometry(page, label) {
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector)
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      shell: rect('.app-shell'),
      toolbar: rect('.resources-page .learning-toolbar'),
      workspace: rect('.resources-page .learning-workspace'),
      shelf: rect('.resources-page .resource-shelf'),
      reader: rect('.resources-page .reading-stage'),
      activeResource: rect('.resources-page .resource-item.is-active'),
      focusMode: document.querySelector('.resources-layout')?.classList.contains('is-focus-mode') || false,
    }
  })
  assert.ok(metrics.toolbar, label + ': learning toolbar should remain present')
  assert.ok(metrics.workspace, label + ': learning workspace should remain present')
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, label + ': Resources view should not create page-level horizontal overflow')
  if (!metrics.focusMode && metrics.shelf && metrics.reader) {
    const overlapX = Math.min(metrics.shelf.right, metrics.reader.right) - Math.max(metrics.shelf.left, metrics.reader.left)
    const overlapY = Math.min(metrics.shelf.bottom, metrics.reader.bottom) - Math.max(metrics.shelf.top, metrics.reader.top)
    assert.ok(overlapX <= 1 || overlapY <= 1, label + ': resource shelf and reader should not overlap')
  }
  evidence.layoutChecks.push({ label, resourcesView: metrics })
  return metrics
}

async function assertResourcesControls(page, label, selectors) {
  const controls = await page.evaluate((items) => items.map((selector) => {
    const node = document.querySelector(selector)
    if (!node) return { selector, missing: true }
    const rect = node.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return {
      selector,
      text: node.innerText?.trim() || node.getAttribute('aria-label') || '',
      visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden',
      rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
      viewport: { width: innerWidth, height: innerHeight },
      unobscured: Boolean(hit && (hit === node || node.contains(hit))),
    }
  }), selectors)
  for (const control of controls) {
    assert.equal(control.missing, undefined, label + ': expected control is missing: ' + control.selector)
    assert.equal(control.visible, true, label + ': control should be visible: ' + JSON.stringify(control))
    assert.ok(control.rect.width >= 44 && control.rect.height >= 44, label + ': primary control should have a 44px target: ' + JSON.stringify(control))
    assert.ok(control.rect.left >= -1 && control.rect.right <= control.viewport.width + 1
      && control.rect.top >= -1 && control.rect.bottom <= control.viewport.height + 1,
    label + ': control should not be clipped outside the viewport: ' + JSON.stringify(control))
    assert.equal(control.unobscured, true, label + ': control center should remain unobscured: ' + JSON.stringify(control))
  }
  evidence.layoutChecks.push({ label, resourcesControls: controls })
}

async function assertResourcesMobileSidebarGeometry(page, label, collapsed) {
  const expectedNavigation = [
    { label: '工作台', href: '/dashboard' },
    { label: '新建方向', href: '/learning/new' },
    { label: '资源生成', href: '/generate' },
    { label: '学习资源', href: '/resources' },
    { label: '学习反馈', href: '/feedback' },
  ]
  const metrics = await page.evaluate((expected) => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const nav = [...document.querySelectorAll('.sidebar .nav-list .nav-item')].map((node) => {
      const box = rect(node)
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
      return {
        label: node.getAttribute('aria-label'),
        href: node.getAttribute('href'),
        current: node.getAttribute('aria-current'),
        rect: box,
        centerHitsTarget: Boolean(hit && (hit === node || node.contains(hit))),
      }
    })
    const button = (selector) => {
      const node = document.querySelector(selector)
      if (!node) return null
      const box = rect(node)
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
      return {
        label: node.getAttribute('aria-label'),
        expanded: node.getAttribute('aria-expanded'),
        rect: box,
        centerHitsTarget: Boolean(hit && (hit === node || node.contains(hit))),
      }
    }
    const brand = document.querySelector('.sidebar .brand-block')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      collapsed: document.querySelector('.app-shell')?.classList.contains('is-sidebar-collapsed') || false,
      brand: brand ? { display: getComputedStyle(brand).display, visible: brand.getClientRects().length > 0 } : null,
      nav,
      toggle: button('.sidebar .sidebar-toggle'),
      logout: button('.sidebar .logout-button'),
      expected,
    }
  }, expectedNavigation)
  assert.equal(metrics.collapsed, collapsed, label + ': sidebar should retain the requested expanded/collapsed state')
  assert.deepEqual(metrics.brand, { display: 'none', visible: false }, label + ': small-screen Resources view should hide the brand block')
  assert.equal(metrics.nav.length, expectedNavigation.length, label + ': all five navigation links should remain present')
  for (let index = 0; index < expectedNavigation.length; index += 1) {
    const item = metrics.nav[index]
    const expected = expectedNavigation[index]
    assert.equal(item.label, expected.label, label + ': navigation aria-label should remain unchanged')
    assert.equal(item.href, expected.href, label + ': navigation href should remain unchanged')
    assert.equal(item.current, expected.href === '/resources' ? 'page' : null,
      label + ': current route semantics should remain on the Resources navigation item')
    assert.ok(item.rect.width >= 44 && item.rect.height >= 44, label + ': each navigation link needs a 44px target: ' + JSON.stringify(item))
    assert.ok(item.rect.left >= -1 && item.rect.right <= metrics.viewport.width + 1
      && item.rect.top >= -1 && item.rect.bottom <= metrics.viewport.height + 1,
    label + ': navigation link should be fully visible: ' + JSON.stringify(item))
    assert.equal(item.centerHitsTarget, true, label + ': navigation link center should hit itself: ' + JSON.stringify(item))
  }
  assert.ok(metrics.toggle, label + ': sidebar toggle should be present')
  assert.ok(metrics.logout, label + ': logout button should be present')
  assert.equal(metrics.toggle.label, collapsed ? '展开侧栏' : '收起侧栏', label + ': toggle aria-label should describe its action')
  assert.equal(metrics.toggle.expanded, collapsed ? 'false' : 'true', label + ': toggle aria-expanded should match its state')
  assert.equal(metrics.logout.label, '退出登录', label + ': logout aria-label should remain unchanged')
  for (const [name, control] of [['toggle', metrics.toggle], ['logout', metrics.logout]]) {
    assert.ok(control.rect.width >= 44 && control.rect.height >= 44, label + ': ' + name + ' needs a 44px target: ' + JSON.stringify(control))
    assert.ok(control.rect.left >= -1 && control.rect.right <= metrics.viewport.width + 1
      && control.rect.top >= -1 && control.rect.bottom <= metrics.viewport.height + 1,
    label + ': ' + name + ' should be fully visible: ' + JSON.stringify(control))
    assert.equal(control.centerHitsTarget, true, label + ': ' + name + ' center should hit itself: ' + JSON.stringify(control))
  }
  const allTargets = [...metrics.nav.map((item) => ({ name: item.label, ...item.rect })),
    { name: 'sidebar-toggle', ...metrics.toggle.rect }, { name: 'logout', ...metrics.logout.rect }]
  for (let leftIndex = 0; leftIndex < allTargets.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < allTargets.length; rightIndex += 1) {
      const left = allTargets[leftIndex]
      const right = allTargets[rightIndex]
      const overlapWidth = Math.min(left.right, right.right) - Math.max(left.left, right.left)
      const overlapHeight = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top)
      assert.ok(overlapWidth <= 1 || overlapHeight <= 1,
        label + ': navigation/control targets should not overlap: ' + JSON.stringify({ left: left.name, right: right.name, overlapWidth, overlapHeight }))
    }
  }
  evidence.layoutChecks.push({ label, resourcesMobileSidebar: metrics })
  return metrics
}

async function compactTopbarMetrics(page) {
  return page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const topbar = document.querySelector('.app-shell .topbar')
    const title = topbar?.querySelector('.topbar-copy h1')
    const actions = topbar?.querySelector('.topbar-actions')
    const meta = topbar?.querySelector('.topbar-meta')
    const subtitle = topbar?.querySelector('.topbar-copy p')
    return {
      topbar: rect(topbar),
      title: rect(title),
      actions: rect(actions),
      meta: rect(meta),
      subtitle: subtitle ? { display: getComputedStyle(subtitle).display, rect: rect(subtitle) } : null,
      titleText: title?.innerText.trim() || '',
      metaText: meta?.innerText.trim() || '',
      actionCount: actions?.querySelectorAll('button').length || 0,
      actionRects: [...(actions?.querySelectorAll('button') || [])].map(rect),
    }
  })
}

async function assertResourcesCompactTopbar(page, label, reference) {
  const metrics = await compactTopbarMetrics(page)
  assert.ok(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-resources')),
    label + ': Resources route should use its route-scoped compact shell style')
  assert.equal(metrics.titleText, '学习资源', label + ': topbar should retain the Resources page title')
  assert.ok(metrics.metaText.includes('fixture-user'), label + ': compact topbar should retain the current-user metadata')
  assert.equal(metrics.actionCount, 3, label + ': compact topbar should retain the three primary app actions')
  assert.ok(metrics.topbar.height >= 56 && metrics.topbar.height <= 72,
    label + ': desktop topbar should remain compact near the shared 60px workspace header: ' + JSON.stringify(metrics.topbar))
  assert.ok(metrics.title && metrics.actions && metrics.meta, label + ': title, actions, and user metadata should remain present')
  assert.ok(Math.abs((metrics.title.top + metrics.title.bottom) / 2 - (metrics.actions.top + metrics.actions.bottom) / 2) <= 2,
    label + ': title and app actions should share one compact header row')
  assert.ok(metrics.title.right <= metrics.actions.left + 1 && metrics.actions.right <= metrics.meta.left + 1,
    label + ': title, actions, and user metadata should not overlap')
  assert.ok(metrics.subtitle && metrics.subtitle.display === 'none'
    && metrics.subtitle.rect.height <= 1, label + ': legacy page subtitle should not consume topbar height')
  for (const action of metrics.actionRects) {
    assert.ok(action.height >= 44, label + ': shared app actions should retain 44px targets: ' + JSON.stringify(action))
  }
  for (const key of ['topbar', 'title', 'actions', 'meta']) {
    for (const coordinate of ['top', 'bottom', 'left', 'right', 'width', 'height']) {
      assert.ok(Math.abs(metrics[key][coordinate] - reference[key][coordinate]) <= 2,
        label + ': Resources topbar should match the existing generation header geometry (' + key + '.' + coordinate + '): '
        + JSON.stringify({ resources: metrics[key], generation: reference[key] }))
    }
  }
  evidence.layoutChecks.push({ label, compactTopbar: metrics, generationReference: reference })
  return metrics
}

async function assertSelectedResourceVisualState(page, label, selector, inactiveSelector) {
  const styles = await page.evaluate(({ active, inactive }) => {
    const describe = (node) => {
      if (!node) return null
      const style = getComputedStyle(node)
      return {
        color: style.color,
        backgroundColor: style.backgroundColor,
        backgroundImage: style.backgroundImage,
        borderColor: style.borderColor,
      }
    }
    return {
      active: describe(document.querySelector(active)),
      inactive: describe(document.querySelector(inactive)),
    }
  }, { active: selector, inactive: inactiveSelector })
  assert.ok(styles.active && styles.inactive, label + ': selected and unselected resources should both be rendered')
  const distinguishable = ['color', 'backgroundColor', 'backgroundImage', 'borderColor']
    .some((key) => styles.active[key] !== styles.inactive[key])
  assert.equal(distinguishable, true, label + ': selected resource should remain visually distinguishable without fixed palette assumptions: ' + JSON.stringify(styles))
  evidence.interactionChecks.push({ label, selectionStyles: styles })
}

async function testStateMatrix(browser, base) {
  for (const scenario of ['queued', 'running', 'sse-fallback', 'completed', 'partial', 'failed', 'no-task', 'no-profile', 'no-output']) {
    const page = await newPage(browser, base, scenario)
    const text = await page.locator('.generate-page').innerText()
    await assertNoLocalHistoryAction(page, scenario)
    assert.equal(await page.locator('.production-intro, .production-banner, .production-context').count(), 0, scenario + ': top-level intro and banner should be removed')
    const summary = await page.locator('.job-summary').innerText()
    for (const semantic of ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']) {
      assert.ok(summary.includes(semantic), scenario + ': missing job summary fact ' + semantic)
    }
    const actionToolbar = page.locator('.resources-panel > .panel-title .task-actions')
    const shouldHaveActions = !['no-task', 'no-profile'].includes(scenario)
    assert.equal(await actionToolbar.count(), shouldHaveActions ? 1 : 0, scenario + ': conditional task controls should be placed under the resource heading')
    if (scenario === 'queued') {
      assert.ok(text.includes('排队中'), 'queued task state should be visible')
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新状态', exact: true }).count(), 'queued job should expose its refresh control in the resource heading')
      await capture(page, 'desktop-pending')
    }
    if (scenario === 'running') {
      assert.ok(text.includes('生成中'), 'running task state should be visible')
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新状态', exact: true }).count(), 'running job should retain refresh in the resource heading')
      assert.ok(text.includes('节点级同步') || text.includes('任务记录'), 'running task should expose stream status')
    }
    if (scenario === 'sse-fallback') {
      await page.locator('.connection-state.is-fallback').waitFor({ state: 'visible' })
      assert.ok(state.requests.some((item) => item.path === '/api/runs/run-main/events'), 'fallback fixture should exercise the real run event endpoint')
      assert.equal(state.sseClients.size, 0, 'the run client should close the unavailable stream before polling')
    }
    if (scenario === 'completed') {
      assert.ok(text.includes('已完成'), 'completed task state should be visible')
      assert.ok(await page.locator('.resource-stage').count(), 'completed task should render the resource reader')
      await assertSummaryAndActions(page, scenario)
      await assertResourcePhases(page, scenario)
      assert.ok((await page.locator('.process-panel .connection-state').innerText()).includes('已结束'), 'terminal run should retain its terminal connection status')
    }
    if (scenario === 'partial') {
      assert.ok(text.includes('失败') || text.includes('审核') || text.includes('重新生成'), 'partial failures should remain visible')
      assert.ok(await actionToolbar.getByRole('button', { name: /重新生成失败资源/ }).count(), 'failed resource batch action should remain in the resource heading')
    }
    if (scenario === 'failed') {
      assert.ok(text.includes('验收任务故障说明'), 'failed task reason should be readable')
      assert.ok(await actionToolbar.getByRole('button', { name: '重新生成', exact: true }).count(), 'failed batch retry should remain in the resource heading')
      await capture(page, 'desktop-failed')
    }
    if (scenario === 'no-task') {
      assert.ok(await page.locator('.empty-studio').isVisible(), 'empty task state should be explicit')
      assert.ok(await page.locator('.empty-studio .preparation-panel').isVisible(), 'no-task state should use the shared preparation panel')
      await assertGenerationPreparationPanel(page, scenario)
      assert.equal(await page.locator('.empty-studio .el-empty').count(), 0, 'no-task state should not retain the legacy empty illustration')
      assert.ok(text.includes('把学习目标，转化为专属内容。'), 'empty task state should explain the next step')
      const primary = page.getByRole('button', { name: '新建学习方向' })
      assert.ok((await primary.boundingBox())?.height >= 44, 'empty state main action should remain at least 44px high')
      await capture(page, 'desktop-empty')
      await page.getByRole('button', { name: '新建学习方向' }).click()
      await assertRouteFixtureReady(page, '/learning/new')
      evidence.interactionChecks.push({ scenario, route: page.url(), action: 'new-learning-direction' })
    }
    if (scenario === 'no-profile') {
      assert.ok(text.includes('学习画像') || text.includes('新建学习方向'), 'no-profile state should remain understandable')
      assert.ok(await page.locator('.empty-studio .preparation-panel').isVisible(), 'no-profile state should use the shared preparation panel')
      await assertGenerationPreparationPanel(page, scenario)
      assert.equal(await page.locator('.empty-studio .el-empty').count(), 0, 'no-profile state should not retain the legacy empty illustration')
      assert.equal(state.profiles.length, 0, 'no-profile fixture should remain empty')
      await capture(page, 'desktop-no-profile')
    }
    if (scenario === 'no-output') {
      await page.locator('.resource-stage[aria-busy="false"]').waitFor({ state: 'visible' })
      const noOutputLayout = await geometry(page, scenario, true)
      assert.ok(noOutputLayout.studio && noOutputLayout.process && noOutputLayout.resources,
        'no-output selected-job state should retain both workbench panels: ' + JSON.stringify(noOutputLayout))
      assert.ok(Math.abs(noOutputLayout.headings.process.top - noOutputLayout.headings.resources.top) <= 1
        && Math.abs(noOutputLayout.headings.process.bottom - noOutputLayout.headings.resources.bottom) <= 1,
      'no-output selected-job state should keep process and resource panel headings aligned: ' + JSON.stringify(noOutputLayout.headings))
      const placeholder = page.locator('.resource-stage .resource-placeholder')
      assert.ok(await placeholder.isVisible(), 'completed task without published output should show a preparation panel inside the resource stage')
      assert.ok(await placeholder.locator('.preparation-heading').isVisible(), 'no-output state should explain the next step with the shared preparation panel')
      const placeholderGeometry = await page.evaluate(() => {
        const stage = document.querySelector('.resource-stage')
        const panel = stage?.querySelector('.resource-placeholder')
        const rect = (node) => {
          if (!node) return null
          const value = node.getBoundingClientRect()
          return { top: value.top, bottom: value.bottom, left: value.left, right: value.right }
        }
        return { stage: rect(stage), panel: rect(panel), contained: Boolean(stage && panel && stage.contains(panel)) }
      })
      assert.equal(placeholderGeometry.contained, true, 'no-output preparation should remain inside the selected-job resource reading region')
      assert.ok(placeholderGeometry.panel.left >= placeholderGeometry.stage.left - 1
        && placeholderGeometry.panel.right <= placeholderGeometry.stage.right + 1
        && placeholderGeometry.panel.top >= placeholderGeometry.stage.top - 1
        && placeholderGeometry.panel.bottom <= placeholderGeometry.stage.bottom + 1,
      'no-output preparation should fit the resource reading region: ' + JSON.stringify(placeholderGeometry))
      assert.equal(await placeholder.locator('.el-empty').count(), 0, 'no-output state should not retain the legacy empty illustration')
      assert.equal(await page.locator('.resource-toolbar').count(), 0, 'no-output state should not offer a reader toolbar without an actual resource')
      assert.equal(await page.locator('.resource-stage .reader-card').count(), 0, 'no-output state should not render a fabricated reader')
      assert.ok(text.includes('已完成'), 'no-output state should preserve the actual completed job status')
      assert.equal(state.jobsByLearner['learner-1'][0]?.job_status, 'completed', 'no-output fixture should have a completed task')
      assert.equal(state.resourcesByRun['run-main'].length, 0, 'no-output fixture must not fabricate published resources')
      await assertSummaryAndActions(page, scenario)
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新资源', exact: true }).count(), 'no-output task should keep its real resource refresh action')
      assert.ok(await actionToolbar.getByRole('button', { name: '追加资源', exact: false }).count(), 'no-output task should keep its append action')
      await capture(page, 'desktop-no-output')
    }
    evidence.scenarios.push({ name: scenario, taskText: text.slice(0, 180) })
    assert.equal(state.writes.length, 0, scenario + ': page entry/state inspection must not write to the fixture API')
    await assertNoExternalOrUnexpected(scenario)
    await page.close()
  }
}

async function assertGenerationPreparationPanel(page, label) {
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const root = document.querySelector('.generate-page')
    const empty = document.querySelector('.empty-studio')
    const panel = empty?.querySelector('.preparation-panel')
    const processHeading = document.querySelector('.process-panel .panel-title')
    const resourcesHeading = document.querySelector('.resources-panel .panel-title')
    const flowArt = empty?.querySelector('.production-flow-art')
    const productionPipeline = flowArt?.querySelector('svg.production-pipeline')
    const capabilityZones = [...(empty?.querySelectorAll('.production-capability-zone') || [])]
    const footer = panel?.querySelector('.preparation-footer')
    const footerAction = footer?.querySelector('button')
    const productionFooter = root?.querySelector(':scope > .production-footer')
    const buttons = [...(panel?.querySelectorAll('button') || [])].map((node) => ({
      ...rect(node), text: node.innerText.trim() || node.getAttribute('aria-label') || '',
    }))
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      root: rect(root), rootScrollWidth: root?.scrollWidth || 0, rootClientWidth: root?.clientWidth || 0,
      empty: rect(empty), panel: rect(panel), processHeading: rect(processHeading), resourcesHeading: rect(resourcesHeading),
      heading: panel?.querySelector('.preparation-heading h3')?.innerText.trim() || '',
      text: panel?.innerText.trim() || '',
      legacyEmptyCount: empty?.querySelectorAll('.el-empty').length || 0,
      productionFlowArt: flowArt && {
        ...rect(flowArt),
        tagName: flowArt.tagName.toLowerCase(),
        visible: flowArt.getClientRects().length > 0 && getComputedStyle(flowArt).display !== 'none' && getComputedStyle(flowArt).visibility !== 'hidden',
        learningPlaneCount: flowArt.querySelectorAll('.learning-plane').length,
      },
      productionPipeline: productionPipeline && {
        ...rect(productionPipeline),
        viewBox: productionPipeline.getAttribute('viewBox'),
        visible: productionPipeline.getClientRects().length > 0 && getComputedStyle(productionPipeline).display !== 'none' && getComputedStyle(productionPipeline).visibility !== 'hidden',
      },
      productionCapabilityZones: capabilityZones.map((node) => ({
        ...rect(node),
        text: node.innerText.trim(),
        visible: node.getClientRects().length > 0 && getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden',
      })),
      footerActionCount: footer?.querySelectorAll('button').length || 0,
      footerAction: footerAction && {
        ...rect(footerAction),
        text: footerAction.innerText.trim() || footerAction.getAttribute('aria-label') || '',
        visible: footerAction.getClientRects().length > 0 && getComputedStyle(footerAction).display !== 'none' && getComputedStyle(footerAction).visibility !== 'hidden',
      },
      productionFooter: rect(productionFooter),
      productionFooterGap: productionFooter && empty
        ? productionFooter.getBoundingClientRect().top - empty.getBoundingClientRect().bottom
        : null,
      studioGrid: Boolean(document.querySelector('.studio-grid')),
      workbenchPanelCount: document.querySelectorAll('.studio-grid > .process-panel, .studio-grid > .resources-panel').length,
      buttons,
    }
  })
  assert.ok(metrics.panel && metrics.heading && metrics.text, `${label}: generation preparation state should have readable structure: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.legacyEmptyCount, 0, `${label}: old Element Plus empty art should not remain: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.productionFlowArt?.tagName === 'figure' && metrics.productionFlowArt.visible,
    `${label}: initial generation should show its visible production flow figure: ${JSON.stringify(metrics.productionFlowArt)}`)
  assert.ok(metrics.productionPipeline?.visible && metrics.productionFlowArt.learningPlaneCount === 0,
    `${label}: production should use its dedicated pipeline drawing instead of the learning-plane SVG: ${JSON.stringify({ art: metrics.productionFlowArt, pipeline: metrics.productionPipeline })}`)
  assert.equal(metrics.productionCapabilityZones.length, 3,
    `${label}: initial generation should retain three capability zones: ${JSON.stringify(metrics.productionCapabilityZones)}`)
  assert.ok(metrics.productionCapabilityZones.every((zone) => zone.visible && zone.text.length > 0),
    `${label}: each initial production capability zone should be visible and readable: ${JSON.stringify(metrics.productionCapabilityZones)}`)
  assert.equal(metrics.footerActionCount, 1,
    `${label}: initial generation should retain one action in its preparation footer: ${JSON.stringify(metrics.footerAction)}`)
  assert.ok(metrics.footerAction?.visible && metrics.footerAction.text.includes('新建学习方向'),
    `${label}: the new-learning action should remain visible in the preparation footer: ${JSON.stringify(metrics.footerAction)}`)
  assert.ok(metrics.productionFooter && metrics.productionFooterGap >= 0 && metrics.productionFooterGap <= 8,
    `${label}: page footer should stay separated from the main preparation area by 0–8px: ${JSON.stringify({ footer: metrics.productionFooter, empty: metrics.empty, gap: metrics.productionFooterGap })}`)
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, `${label}: document horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.rootScrollWidth <= metrics.rootClientWidth + 1, `${label}: generation root horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.panel.left >= metrics.empty.left - 1 && metrics.panel.right <= metrics.empty.right + 1,
    `${label}: preparation panel should fit its resource region: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.studioGrid, false, `${label}: no-task/no-profile state should use the standalone empty-studio layout`)
  assert.equal(metrics.workbenchPanelCount, 0, `${label}: empty-studio state should not render process/resource workbench panels`)
  for (const button of metrics.buttons) {
    assert.ok(button.height >= 44, `${label}: preparation actions should remain 44px targets: ${JSON.stringify(button)}`)
    assert.ok(button.left >= -1 && button.right <= metrics.viewport.width + 1, `${label}: preparation action should not be clipped: ${JSON.stringify(button)}`)
  }
  if (metrics.viewport.width >= 1100) {
    assert.ok(Math.abs(metrics.productionPipeline.height - 220) <= 1,
      `${label}: compact desktop production pipeline should be 220px tall: ${JSON.stringify(metrics.productionPipeline)}`)
    assert.ok(metrics.productionPipeline.top >= metrics.panel.top - 1 && metrics.productionPipeline.bottom <= metrics.panel.bottom + 1,
      `${label}: the 220px production pipeline should fit inside the preparation panel: ${JSON.stringify({ pipeline: metrics.productionPipeline, panel: metrics.panel })}`)
    if (metrics.processHeading && metrics.resourcesHeading) {
      assert.ok(Math.abs(metrics.processHeading.top - metrics.resourcesHeading.top) <= 1
        && Math.abs(metrics.processHeading.bottom - metrics.resourcesHeading.bottom) <= 1,
      `${label}: workbench column headings should stay aligned around the compact preparation area: ${JSON.stringify(metrics)}`)
    } else {
      assert.ok(metrics.empty.width >= metrics.root.width * 0.9,
        `${label}: standalone preparation state should use the available desktop width: ${JSON.stringify(metrics)}`)
    }
  }
  evidence.layoutChecks.push({ label, generationPreparation: metrics })
  return metrics
}

async function assertLearningPreparationState(page, label, { busy = false } = {}) {
  await page.locator('.library-empty.preparation-panel').waitFor({ state: 'visible' })
  const metrics = await page.evaluate(() => {
    const panel = document.querySelector('.library-empty.preparation-panel')
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { x: value.x, y: value.y, right: value.right, bottom: value.bottom, width: value.width, height: value.height }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      page: { scrollWidth: document.querySelector('.resources-page')?.scrollWidth || 0, clientWidth: document.querySelector('.resources-page')?.clientWidth || 0 },
      pageRect: rect(document.querySelector('.resources-page')),
      contentRect: rect(document.querySelector('.content-area')),
      toolbarRect: rect(document.querySelector('.learning-toolbar')),
      panel: rect(panel),
      busy: panel?.getAttribute('aria-busy'),
      heading: panel?.querySelector('.preparation-heading h3')?.innerText.trim() || '',
      text: panel?.innerText.trim() || '',
      preparationHeading: rect(panel?.querySelector('.preparation-heading')),
      preparationSteps: [...(panel?.querySelectorAll('.preparation-steps > li') || [])].map(rect),
      preparationFooter: rect(panel?.querySelector('.preparation-footer')),
      preparationFooterCount: panel?.querySelectorAll('.preparation-footer').length || 0,
      flowArt: (() => {
        const art = panel?.querySelector('.library-flow-art')
        const style = art ? getComputedStyle(art) : null
        return art ? {
          ...rect(art),
          text: art.innerText?.trim() || '',
          childCount: art.children.length,
          visible: art.getClientRects().length > 0 && style.display !== 'none' && style.visibility !== 'hidden',
          learningPlaneCount: art.querySelectorAll('svg.learning-plane').length,
          productionPipelineCount: art.querySelectorAll('svg.production-pipeline').length,
        } : null
      })(),
      flowZones: [...(panel?.querySelectorAll('.library-flow-zone, .library-capability-zone, [data-flow-zone], [data-capability-zone]') || [])]
        .map(node => ({ text: node.innerText.trim(), ...rect(node) })),
      stepsCount: panel?.querySelectorAll('.preparation-steps > li').length || 0,
      legacyEmptyCount: panel?.querySelectorAll('.el-empty').length || 0,
      shelfCount: document.querySelectorAll('.resource-shelf').length,
      readerCount: document.querySelectorAll('.reading-stage .reader-card, .reading-stage .courseware-viewer').length,
      panelButtons: [...(panel?.querySelectorAll('button') || [])].map((node) => {
        const value = node.getBoundingClientRect()
        return { text: node.innerText.trim() || node.getAttribute('aria-label') || '', x: value.x, y: value.y, right: value.right, bottom: value.bottom, width: value.width, height: value.height, visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden' }
      }),
      toolbarButtons: [...document.querySelectorAll('.learning-toolbar button')].map((node) => {
        const value = node.getBoundingClientRect()
        return { text: node.innerText.trim() || node.getAttribute('aria-label') || '', x: value.x, right: value.right, width: value.width, height: value.height, visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden' }
      }),
    }
  })
  assert.ok(metrics.panel, `${label}: learning should show a preparation panel instead of a blank workspace`)
  assert.ok(metrics.heading.length > 0 && metrics.text.length > 0, `${label}: preparation state should have a readable heading and explanation`)
  assert.equal(metrics.busy, String(busy), `${label}: preparation busy state should match the actual resource load: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.legacyEmptyCount, 0, `${label}: the old Element Plus empty illustration should not remain`)
  assert.equal(metrics.shelfCount, 0, `${label}: resource shelf should not appear before any resource is published`)
  assert.equal(metrics.readerCount, 0, `${label}: reader should not be fabricated before a resource exists`)
  assert.equal(metrics.stepsCount, 3, `${label}: learning preparation should retain its three practical next steps`)
  assert.ok(metrics.flowArt?.visible && metrics.flowArt.childCount > 0,
    `${label}: the learning preparation should show its scientific learning-flow mark: ${JSON.stringify(metrics.flowArt)}`)
  assert.equal(metrics.flowArt.learningPlaneCount, 1,
    `${label}: library preparation should preserve its original learning-plane illustration: ${JSON.stringify(metrics.flowArt)}`)
  assert.equal(metrics.flowArt.productionPipelineCount, 0,
    `${label}: the production pipeline should remain separate from the learning illustration: ${JSON.stringify(metrics.flowArt)}`)
  assert.ok(metrics.flowZones.length === 3 && metrics.flowZones.every(zone => zone.text.length > 0),
    `${label}: the flow illustration should expose three readable capability zones: ${JSON.stringify(metrics.flowZones)}`)
  assert.ok(metrics.document.scrollWidth <= metrics.document.clientWidth + 1, `${label}: document horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.page.scrollWidth <= metrics.page.clientWidth + 1, `${label}: Resources page horizontal overflow: ${JSON.stringify(metrics)}`)
  for (const target of [...metrics.panelButtons, ...metrics.toolbarButtons]) {
    if (!target.visible) continue
    assert.ok(target.height >= 44, `${label}: preparation action must remain a 44px target: ${JSON.stringify(target)}`)
    assert.ok(target.x >= -1 && target.right <= metrics.viewport.width + 1, `${label}: preparation action should fit the viewport: ${JSON.stringify(target)}`)
  }
  if (metrics.viewport.width >= 1100) {
    assert.ok(metrics.contentRect && metrics.toolbarRect, `${label}: desktop preparation should be measured against the available content height`)
    assert.ok(metrics.panel.bottom <= metrics.contentRect.bottom + 1 && metrics.panel.bottom >= metrics.contentRect.bottom - 32,
      `${label}: desktop preparation should use the available lower workspace instead of leaving a large blank tail: ${JSON.stringify({ panel: metrics.panel, content: metrics.contentRect })}`)
    if (!busy) {
      assert.ok(metrics.preparationFooter && metrics.preparationFooterCount === 1,
        `${label}: settled desktop preparation should retain its action footer`)
      assert.ok(metrics.preparationFooter.bottom >= metrics.panel.bottom - 48,
        `${label}: desktop footer should remain near the bottom of the expanded preparation area: ${JSON.stringify({ footer: metrics.preparationFooter, panel: metrics.panel })}`)
      for (const button of metrics.panelButtons.filter(item => item.visible)) {
        assert.ok(button.bottom <= metrics.viewport.height + 1,
          `${label}: settled desktop preparation actions should be visible without scrolling: ${JSON.stringify(button)}`)
      }
    }
  }
  evidence.layoutChecks.push({ label, learningPreparation: metrics })
  return metrics
}

async function assertLearningPreparationActionsReachable(page, label) {
  const actions = page.locator('.library-empty.preparation-panel button:visible')
  const count = await actions.count()
  assert.ok(count > 0, `${label}: mobile preparation state should expose an existing action`)
  for (let index = 0; index < count; index += 1) {
    const action = actions.nth(index)
    await action.scrollIntoViewIfNeeded()
    const metrics = await action.evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return {
        text: node.innerText.trim() || node.getAttribute('aria-label') || '',
        viewport: { width: innerWidth, height: innerHeight },
        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
        visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden',
      }
    })
    assert.ok(metrics.visible && metrics.rect.height >= 44, `${label}: preparation action should remain visible and at least 44px high: ${JSON.stringify(metrics)}`)
    assert.ok(metrics.rect.left >= -1 && metrics.rect.right <= metrics.viewport.width + 1
      && metrics.rect.top >= -1 && metrics.rect.bottom <= metrics.viewport.height + 1,
    `${label}: natural scrolling should make each preparation action fully reachable: ${JSON.stringify(metrics)}`)
    evidence.layoutChecks.push({ label: `${label}-action-${index + 1}`, learningPreparationAction: metrics })
  }
}

async function assertLearningPrimaryVisualAndFocus(page, label) {
  const primary = page.locator('.library-empty .library-preparation-actions .el-button--primary:visible')
  assert.equal(await primary.count(), 1, `${label}: the initial learning state should expose one visible body primary action`)
  const initial = await primary.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    const style = getComputedStyle(node)
    return {
      text: node.innerText.trim(),
      rect: { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, height: rect.height },
      color: style.color,
      backgroundColor: style.backgroundColor,
      backgroundImage: style.backgroundImage,
      borderColor: style.borderColor,
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    }
  })
  assert.ok(initial.rect.height >= 44, `${label}: primary action should remain a 44px target: ${JSON.stringify(initial)}`)
  const contrastStart = evidence.contrastChecks.length
  await assertContrast(page, label)
  const contrastChecks = evidence.contrastChecks.slice(contrastStart).flatMap(item => item.checks)
    .filter(item => item.selector === '.library-empty .library-preparation-actions .el-button--primary')
  assert.equal(contrastChecks.length, 1, `${label}: contrast should be measured on the visible body primary only: ${JSON.stringify(contrastChecks)}`)
  assert.ok(contrastChecks[0].contrast >= 4.5, `${label}: initial-state primary contrast should be at least 4.5:1: ${JSON.stringify(contrastChecks[0])}`)

  await primary.focus()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Shift+Tab')
  await page.waitForTimeout(50)
  const focused = await primary.evaluate((node) => {
    const style = getComputedStyle(node)
    return {
      active: document.activeElement === node,
      focusVisible: node.matches(':focus-visible'),
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    }
  })
  assert.equal(focused.active, true, `${label}: primary action should retain keyboard focus`)
  assert.equal(focused.focusVisible, true, `${label}: primary action should expose keyboard focus-visible styling`)
  assert.ok((focused.outlineStyle !== 'none' && Number.parseFloat(focused.outlineWidth) >= 2)
    || (focused.boxShadow !== 'none' && focused.boxShadow !== initial.boxShadow),
  `${label}: keyboard focus ring should be visible: ${JSON.stringify({ initial, focused })}`)
  evidence.interactionChecks.push({ label, initial, contrast: contrastChecks[0], focused })
}

async function openLearningPreparationPage(browser, base, scenario, viewport = baseViewport, { delayJobsMs = 0 } = {}) {
  const page = await newPage(browser, base, scenario, viewport)
  if (delayJobsMs) state.jobsDelayMs = delayJobsMs
  await page.goto(base + '/resources?learnerId=learner-1&runId=run-main', { waitUntil: 'domcontentloaded' })
  await page.locator('.resources-layout').waitFor({ state: 'visible' })
  return page
}

async function testPreparationResponsiveStates(browser, base) {
  const generationPage = await newPage(browser, base, 'no-task')
  try {
    for (const viewport of [{ width: 390, height: 844 }, { width: 375, height: 667 }]) {
      await generationPage.setViewportSize(viewport)
      await generationPage.evaluate(() => {
        document.querySelector('.content-area')?.scrollTo(0, 0)
        document.querySelector('.generate-page')?.scrollTo(0, 0)
      })
      await waitForLayout(generationPage, false)
      const metrics = await geometry(generationPage, `generation-empty-${viewport.width}x${viewport.height}`, false)
      const preparation = generationPage.locator('.empty-studio .preparation-panel')
      assert.ok(await preparation.isVisible(), 'mobile no-task state should retain its preparation panel')
      await assertGenerationPreparationPanel(generationPage, `mobile-${viewport.width}x${viewport.height}`)
      assert.equal(await generationPage.locator('.empty-studio .el-empty').count(), 0, 'mobile no-task state should not show the legacy empty illustration')
      const primary = generationPage.getByRole('button', { name: '新建学习方向' })
      await primary.scrollIntoViewIfNeeded()
      const rect = await primary.boundingBox()
      assert.ok(rect && rect.height >= 44 && rect.x >= -1 && rect.x + rect.width <= viewport.width + 1, 'mobile preparation action should remain reachable without horizontal clipping: ' + JSON.stringify({ viewport, rect }))
      assert.ok(rect.y >= -1 && rect.y + rect.height <= viewport.height + 1, 'mobile preparation action should be reachable by natural scrolling: ' + JSON.stringify({ viewport, rect, document: metrics.document }))
      await capture(generationPage, `mobile-empty-${viewport.width}x${viewport.height}`)
    }
    const shortViewport = { width: 1280, height: 640 }
    await generationPage.setViewportSize(shortViewport)
    await generationPage.evaluate(() => {
      document.querySelector('.content-area')?.scrollTo(0, 0)
      document.querySelector('.generate-page')?.scrollTo(0, 0)
    })
    await waitForLayout(generationPage)
    await assertGenerationPreparationPanel(generationPage, 'short-window-1280x640')
    const shortAction = generationPage.getByRole('button', { name: '新建学习方向' })
    await shortAction.scrollIntoViewIfNeeded()
    const shortRect = await shortAction.boundingBox()
    assert.ok(shortRect && shortRect.height >= 44 && shortRect.y >= -1 && shortRect.y + shortRect.height <= shortViewport.height + 1,
      'short-window preparation action should remain reachable by natural scrolling: ' + JSON.stringify({ shortViewport, rect: shortRect }))
    await capture(generationPage, 'generation-empty-1280x640-short')
    assert.equal(state.writes.length, 0, 'mobile empty-state inspection must not write to the fixture API')
    await assertNoExternalOrUnexpected('generation-empty-mobile')
  } finally { await generationPage.close() }
}

async function testLearningPreparationStates(browser, base) {
  const loadingPage = await openLearningPreparationPage(browser, base, 'no-task', baseViewport, { delayJobsMs: 500 })
  try {
    const loading = loadingPage.locator('.library-empty.preparation-panel')
    await loading.waitFor({ state: 'visible' })
    await loadingPage.waitForFunction(() => document.querySelector('.library-empty.preparation-panel')?.getAttribute('aria-busy') === 'true')
    await assertLearningPreparationState(loadingPage, 'learning-initial-loading', { busy: true })
    await capture(loadingPage, 'resources-preparation-loading')
    await loadingPage.waitForFunction(() => document.querySelector('.library-empty.preparation-panel')?.getAttribute('aria-busy') === 'false', null, { timeout: 8000 })
    await assertLearningPreparationState(loadingPage, 'learning-loading-settled')
    evidence.scenarios.push({ name: 'learning-initial-loading', busyObserved: true, settled: true })
    assert.equal(state.writes.length, 0, 'learning initial loading should remain read-only')
    await assertNoExternalOrUnexpected('learning-initial-loading')
  } finally { await loadingPage.close() }

  const noProfilePage = await openLearningPreparationPage(browser, base, 'no-profile', { width: 390, height: 844 })
  let noProfileHeading = ''
  try {
    const metrics = await assertLearningPreparationState(noProfilePage, 'learning-no-profile')
    noProfileHeading = metrics.heading
    assert.equal(state.profiles.length, 0, 'no-profile learning fixture must contain no profiles')
    assert.ok(/画像|方向/.test(metrics.text), 'no-profile preparation should explain the missing learning profile')
    const create = noProfilePage.getByRole('button', { name: '新建学习方向' })
    assert.ok(await create.isVisible(), 'no-profile preparation should preserve the existing create-direction entry')
    await capture(noProfilePage, 'resources-preparation-no-profile')
    await assertLearningPrimaryVisualAndFocus(noProfilePage, 'learning-preparation-primary-cta')
    await assertLearningPreparationActionsReachable(noProfilePage, 'learning-no-profile-mobile')
    await capture(noProfilePage, 'resources-preparation-no-profile-action-reachable')
    evidence.scenarios.push({ name: 'learning-no-profile', profiles: state.profiles.length })
    assert.equal(state.writes.length, 0, 'no-profile state inspection must not create real business records')
    await assertNoExternalOrUnexpected('learning-no-profile')
  } finally { await noProfilePage.close() }

  const noTaskPage = await openLearningPreparationPage(browser, base, 'no-task', { width: 390, height: 844 })
  let noTaskHeading = ''
  try {
    const metrics = await assertLearningPreparationState(noTaskPage, 'learning-no-task')
    noTaskHeading = metrics.heading
    assert.ok(state.profiles.length > 0, 'no-task learning fixture should retain an existing profile')
    assert.equal(state.jobsByLearner['learner-1'].length, 0, 'no-task learning fixture should contain no generation task')
    assert.ok(/任务|资源|生成|学习/.test(metrics.text), 'no-task preparation should explain that resources or a task are missing')
    assert.ok(await noTaskPage.getByRole('button', { name: '新建学习方向' }).isVisible(), 'no-task preparation should preserve the existing create-direction entry')
    assert.notEqual(noTaskHeading, noProfileHeading, 'no-profile and no-task states should give distinct guidance')
    await capture(noTaskPage, 'resources-preparation-no-task-390x844')
    await assertLearningPreparationActionsReachable(noTaskPage, 'learning-no-task-mobile')
    await capture(noTaskPage, 'resources-preparation-no-task-actions-reachable')
    evidence.scenarios.push({ name: 'learning-no-task', jobs: state.jobsByLearner['learner-1'].length })
    assert.equal(state.writes.length, 0, 'no-task state inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-no-task')
  } finally { await noTaskPage.close() }

  const waitingPage = await openLearningPreparationPage(browser, base, 'queued')
  try {
    const metrics = await assertLearningPreparationState(waitingPage, 'learning-task-waiting-no-resources')
    assert.equal(state.jobsByLearner['learner-1'][0]?.job_status, 'queued', 'waiting learning fixture should retain the queued task state')
    assert.equal(state.resourcesByRun['run-main'].length, 0, 'waiting learning fixture must not fabricate published resources')
    assert.ok(/排队|等待|生成|准备/.test(metrics.text), 'waiting state should communicate that real task output is still pending')
    assert.notEqual(metrics.heading, noTaskHeading, 'waiting-for-output guidance should differ from the no-task state')
    await capture(waitingPage, 'resources-preparation-task-waiting')
    evidence.scenarios.push({ name: 'learning-task-waiting-no-resources', status: state.jobsByLearner['learner-1'][0]?.job_status, resources: state.resourcesByRun['run-main'].length })
    assert.equal(state.writes.length, 0, 'waiting-state inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-task-waiting-no-resources')
  } finally { await waitingPage.close() }

  const desktopCollapsedPage = await openLearningPreparationPage(browser, base, 'no-task', { width: 1331, height: 871 })
  try {
    await setResourcesSidebar(desktopCollapsedPage, true)
    const metrics = await assertLearningPreparationState(desktopCollapsedPage, 'learning-no-task-1331x871-collapsed')
    assert.equal(state.jobsByLearner['learner-1'].length, 0, 'collapsed desktop learning fixture should remain in the no-task state')
    assert.ok(metrics.panel.bottom >= metrics.contentRect.bottom - 32, 'collapsed desktop preparation should still use the available lower workspace')
    await capture(desktopCollapsedPage, 'resources-preparation-no-task-1331x871-collapsed')
    assert.equal(state.writes.length, 0, 'collapsed desktop preparation inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-no-task-1331x871-collapsed')
  } finally { await desktopCollapsedPage.close() }
}

async function testDesktopFitMatrix(browser, base) {
  const viewports = [
    { width: 1393, height: 871 },
    { width: 1331, height: 871 },
    { width: 1440, height: 900 },
    { width: 1280, height: 640 },
  ]
  const page = await newPage(browser, base, 'long', viewports[0])
  await page.waitForFunction(() => (document.querySelector('.process-scroll')?.scrollHeight || 0) > (document.querySelector('.process-scroll')?.clientHeight || Infinity))
  await page.waitForFunction(() => (document.querySelector('.resource-stage')?.scrollHeight || 0) > (document.querySelector('.resource-stage')?.clientHeight || Infinity))
  await assertResourcePhases(page, 'long-desktop', { longMetadata: true })
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await waitForLayout(page, true)
    for (const collapsed of [false, true]) {
      await setSidebar(page, collapsed)
      const label = viewport.width + 'x' + viewport.height + (collapsed ? '-collapsed' : '-expanded')
      const metrics = await geometry(page, label, true)
      assert.ok(Math.abs(metrics.headings.process.top - metrics.headings.resources.top) <= 1, label + ': panel headings differ vertically')
      if (viewport.width === 1393 && !collapsed) await capture(page, 'desktop-long-expanded')
      if (viewport.width === 1393 && collapsed) await capture(page, 'desktop-long-collapsed')
    }
  }
  await page.setViewportSize({ width: 1393, height: 871 })
  await setSidebar(page, true)
  await assertInternalScroll(page, '1393x871-long-collapsed')
  await assertContrast(page, '1393x871-long-collapsed')
  await capture(page, 'desktop-long-scrolled')
  await assertNoExternalOrUnexpected('desktop-fit-matrix')
  await page.close()
}

async function testNaturalFallback(browser, base) {
  const viewports = [
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
    { width: 375, height: 667 },
    { width: 844, height: 390 },
  ]
  const page = await newPage(browser, base, 'long', viewports[0])
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await waitForLayout(page, false)
    await page.evaluate(() => {
      window.scrollTo(0, 0)
      const area = document.querySelector('.content-area')
      if (area) area.scrollTop = 0
      const root = document.querySelector('.generate-page')
      if (root) root.scrollTop = 0
    })
    const label = viewport.width + 'x' + viewport.height + '-natural'
    const metrics = await geometry(page, label)
    assert.ok(metrics.document.width <= viewport.width + 1, label + ': no horizontal overflow')
    assert.ok(metrics.externalOverflow.length === 0, label + ': visible content extends beyond the viewport: ' + JSON.stringify(metrics.externalOverflow))
    if (viewport.width === 390) await capture(page, 'mobile-top')
    await page.evaluate(() => {
      const area = document.querySelector('.content-area')
      if (area) area.scrollTop = area.scrollHeight
      window.scrollTo(0, document.documentElement.scrollHeight)
      const resource = document.querySelector('.resource-stage')
      if (resource) resource.scrollTop = resource.scrollHeight
    })
    const pageScroll = await page.evaluate(() => document.documentElement.scrollTop + (document.querySelector('.content-area')?.scrollTop || 0))
    const markdownEnd = await page.getByText('这是滚动到正文末尾后应当完整可读的标记。', { exact: true }).count()
    assert.equal(markdownEnd, 1, label + ': long markdown tail must remain in the document')
    const endIsReachable = await page.getByText('这是滚动到正文末尾后应当完整可读的标记。', { exact: true }).evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return rect.top >= -1 && rect.bottom <= innerHeight + 1
    })
    assert.equal(endIsReachable, true, label + ': scrolling should expose the full long-markdown tail')
    assert.ok(pageScroll > 0, label + ': natural fallback should allow page-area scrolling')
    const learningButton = page.locator('.learning-mode-action')
    if (await learningButton.count()) {
      const buttonHeight = await learningButton.evaluate((node) => node.getBoundingClientRect().height)
      assert.ok(buttonHeight >= 44, label + ': main learning action should remain at least 44px high')
    }
    if (viewport.width === 390) await capture(page, 'mobile-long-natural')
  }
  await assertNoExternalOrUnexpected('natural-fallback-matrix')
  await page.close()
}

async function testSwitchesRefreshAndErrors(browser, base) {
  const page = await newPage(browser, base, 'multi', baseViewport, { delayJobsMs: 350 })
  await chooseOption(page, '资源批次', /run-queu/i)
  assert.ok((await page.locator('.generate-page').innerText()).includes('排队中'), 'batch selector should switch to queued run')
  await page.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/generate/jobs/run-queued'), 'selected run status refresh')
  const statusRequests = state.requests.filter((item) => item.path === '/api/generate/jobs/run-queued')
  assert.ok(statusRequests.length >= 1, 'refresh should request the selected job status')
  await chooseOption(page, '学习画像', /周明远/)
  await page.waitForFunction(() => document.querySelector('.generate-page')?.textContent.includes('数据工程'))
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/run-alt/timeline'), 'profile switch default-run timeline')
  assert.equal((await page.locator('.summary-code').innerText()).trim(), 'RUN-ALT', 'profile switch should select the new profile default run')
  evidence.interactionChecks.push({ scenario: 'multi', selectedProfile: 'learner-2', selectedRun: 'run-queued', statusRequests: statusRequests.length })
  await assertNoExternalOrUnexpected('switch-and-refresh')
  await page.close()

  const deletePage = await newPage(browser, base, 'multi')
  await deletePage.getByRole('combobox', { name: '学习画像' }).click()
  await deletePage.locator('.profile-select-dropdown').locator('.profile-delete').first().click()
  const deleteDialog = deletePage.getByRole('dialog').filter({ hasText: '删除学习画像' })
  await deleteDialog.waitFor({ state: 'visible' })
  assert.ok((await deleteDialog.innerText()).includes('此操作无法撤销'), 'profile delete dialog should explain the confirmation')
  await deleteDialog.getByRole('button', { name: '取消', exact: true }).click()
  await deleteDialog.waitFor({ state: 'hidden' })
  assert.equal(state.writes.length, 0, 'cancelling profile deletion must not write to the fixture API')
  evidence.interactionChecks.push({ scenario: 'profile-delete-cancel', cancelled: true })
  await assertNoExternalOrUnexpected('profile-delete-confirm')
  await deletePage.close()

  const errorPage = await newPage(browser, base, 'running', baseViewport, { failStatus: 1 })
  await errorPage.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await errorPage.getByText('任务状态获取失败').waitFor({ state: 'visible' })
  assert.ok((await errorPage.locator('.generate-page').innerText()).includes('生成中'), 'a status failure should keep the current task readable')
  evidence.interactionChecks.push({ scenario: 'running-status-error', statusFailure: true })
  await assertNoExternalOrUnexpected('status-error-feedback')
  await errorPage.close()

  const resourcePage = await newPage(browser, base, 'completed', baseViewport, { delayResourcesMs: 450, failResources: 1 })
  await resourcePage.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: '刷新资源', exact: true }).click()
  assert.ok(await resourcePage.locator('.resource-stage .el-loading-mask').count(), 'resource refresh should expose a loading state')
  await resourcePage.getByText('资源列表加载失败').waitFor({ state: 'visible' })
  evidence.interactionChecks.push({ scenario: 'resource-load-error', loadingAndError: true })
  await assertNoExternalOrUnexpected('resource-error-feedback')
  await resourcePage.close()
}

async function testResourceSwitchAndLearningRoutes(browser, base) {
  const page = await newPage(browser, base, 'long', baseViewport)
  assert.ok(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-generation')),
    'generation route should provide the shared compact-topbar reference')
  const generationTopbar = await compactTopbarMetrics(page)
  await page.locator('.resource-content h1').waitFor({ state: 'visible' })
  const longResourceType = '多阶段知识迁移与证据核验实操指南资源类型'
  const resourceSelect = page.locator('.resource-select')
  await assertWrappedFieldFocus(page, 'generation-resource-select', resourceSelect.locator('input').first(), resourceSelect.locator('.el-select__wrapper'), 'focus-generation-resource-select')
  await resourceSelect.click()
  const fullLongOption = page.getByRole('option', { name: new RegExp(longResourceType) })
  await fullLongOption.waitFor({ state: 'visible' })
  assert.ok((await fullLongOption.innerText()).includes(longResourceType), 'resource option should retain the full accessible long type')
  await page.keyboard.press('Escape')
  const longDocumentTitle = page.locator('.resource-content h1')
  assert.ok((await longDocumentTitle.innerText()).includes(longResourceType + ' · 节点A、节点B'), 'resource body title should retain the complete long resource identity')
  await geometry(page, '1393x871-long-kind-tools', true)
  await capture(page, 'desktop-long-kind-tools')
  await page.setViewportSize({ width: 390, height: 844 })
  await waitForLayout(page, false)
  await page.evaluate(() => {
    document.documentElement.scrollTop = 0
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.generate-page')?.scrollTo(0, 0)
    document.querySelector('.resource-stage')?.scrollTo(0, 0)
  })
  await geometry(page, '390x844-long-kind-tools', false)
  await capture(page, 'mobile-long-kind-tools')
  const popupPromise = page.waitForEvent('popup')
  await page.locator('.resource-toolbar .download-button').click()
  const downloadPopup = await popupPromise
  await downloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(downloadPopup.url()).pathname, '/api/resources/file/resource-guide', 'reader download should open only the fixture file route')
  assert.ok((await downloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-guide'), 'fixture download response should remain readable')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-guide'), 'download action should make a read-only fixture request')
  evidence.interactionChecks.push({ scenario: 'reader-download', url: downloadPopup.url(), method: 'GET' })
  await downloadPopup.close()
  await page.setViewportSize(baseViewport)
  await waitForLayout(page, true)
  await page.locator('.resource-stage').evaluate((node) => { node.scrollTop = Math.min(400, node.scrollHeight) })
  await chooseFilterableOptionWithKeyboard(page, resourceSelect, '复习清单', '复习清单', 'generation-resource-select')
  await page.waitForFunction(() => document.querySelector('.resource-stage')?.scrollTop === 0)
  await page.waitForFunction(() => document.querySelector('.resource-content h1')?.textContent.includes('复习清单'))
  const readerTitle = page.locator('.resource-content h1')
  assert.ok((await readerTitle.innerText()).includes('复习清单'), 'resource selector should switch the visible resource')
  await capture(page, 'desktop-resource-switched')
  const switchedDownloadPopupPromise = page.waitForEvent('popup')
  await page.locator('.resource-toolbar .download-button').click()
  const switchedDownloadPopup = await switchedDownloadPopupPromise
  await switchedDownloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(switchedDownloadPopup.url()).pathname, '/api/resources/file/resource-checklist', 'download should follow the newly selected resource')
  assert.ok((await switchedDownloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-checklist'), 'switched resource download should return its matching fixture')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-checklist'), 'switched resource download should use the local fixture endpoint')
  evidence.interactionChecks.push({ scenario: 'reader-download-after-switch', url: switchedDownloadPopup.url(), method: 'GET', resourceId: 'resource-checklist' })
  await switchedDownloadPopup.close()
  await page.getByRole('button', { name: '学习模式', exact: true }).click()
  await assertRouteFixtureReady(page, '/resources')
  assert.equal(new URL(page.url()).searchParams.get('learnerId'), 'learner-1')
  assert.equal(new URL(page.url()).searchParams.get('runId'), 'batch-learner-1')
  evidence.interactionChecks.push({ scenario: 'completed', route: page.url(), action: 'learning-mode' })
  const libraryReader = page.locator('.resources-page .reader-card')
  await libraryReader.locator('.reader-header').waitFor({ state: 'visible' })
  await libraryReader.locator('.resource-content h1').waitFor({ state: 'visible' })
  const initialLibraryTitle = (await libraryReader.locator('.resource-content h1').innerText()).trim()
  const resourcesProfileSelect = page.locator('.resources-page .learning-toolbar .el-select').nth(0)
  const resourcesBatchSelect = page.locator('.resources-page .learning-toolbar .el-select').nth(1)
  await assertWrappedFieldFocus(page, 'resources-toolbar-profile', resourcesProfileSelect.locator('input'), resourcesProfileSelect.locator('.el-select__wrapper'))
  await chooseFilterableOptionWithKeyboard(page, resourcesProfileSelect, 'AI 应用开发', 'AI 应用开发', 'resources-toolbar-profile')
  await assertWrappedFieldFocus(page, 'resources-toolbar-batch', resourcesBatchSelect.locator('input'), resourcesBatchSelect.locator('.el-select__wrapper'))
  await chooseFilterableOptionWithKeyboard(page, resourcesBatchSelect, '资源批次 01', '资源批次 01', 'resources-toolbar-batch')
  await page.waitForFunction((expectedTitle) => document.querySelector('.resources-page .resource-content h1')?.textContent.trim() === expectedTitle, initialLibraryTitle)
  assert.equal((await libraryReader.locator('.resource-content h1').innerText()).trim(), initialLibraryTitle,
    'selecting the existing profile and batch should preserve the currently selected resource')
  await setResourcesSidebar(page, false)
  await assertResourcesGeometry(page, 'resources-1393x871-expanded')
  await assertResourcesCompactTopbar(page, 'resources-1393x871-compact-topbar', generationTopbar)
  assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed')), false,
    'Resources view desktop baseline should have the sidebar expanded')
  await assertResourcesControls(page, 'resources-1393x871-expanded', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
    '.resources-page .resource-feedback-button',
    '.resources-page .tutor-trigger',
  ])
  assert.equal(await libraryReader.locator('.reader-header .resource-kicker').count(), 1, 'default learning route should retain the reader header fallback')
  assert.equal(await libraryReader.locator('.reader-header .reader-actions .el-tag').count(), 1, 'default learning route should retain the difficulty label')
  assert.ok(await libraryReader.locator('.reader-header .download-button').isVisible(), 'default learning route should retain reader download')
  const defaultDocumentTitle = libraryReader.locator('.resource-content h1')
  await defaultDocumentTitle.waitFor({ state: 'visible' })
  assert.ok((await defaultDocumentTitle.innerText()).includes('讲义'), 'default learning route should load its selected reader resource')
  await capture(page, 'desktop-default-learning-reader')
  await assertContrast(page, 'resources-ordinary-reader')
  const defaultDownloadPopupPromise = page.waitForEvent('popup')
  await libraryReader.locator('.reader-header .download-button').click()
  const defaultDownloadPopup = await defaultDownloadPopupPromise
  await defaultDownloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(defaultDownloadPopup.url()).pathname, '/api/resources/file/resource-lecture', 'default reader should keep the original download callback and selected resource')
  assert.ok((await defaultDownloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-lecture'), 'default reader download should return its local fixture response')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-lecture'), 'default reader download should use the local fixture endpoint')
  await defaultDownloadPopup.close()
  assert.ok(await libraryReader.locator('.reader-header .tutor-trigger').isVisible(), 'default ResourceViewer header-end-actions slot should still render its caller button')
  await libraryReader.locator('.reader-header .tutor-trigger').click()
  await page.locator('.tutor-panel').waitFor({ state: 'visible' })
  await page.getByText('从卡住的地方开始', { exact: true }).waitFor({ state: 'visible' })
  const tutorCreate = state.writes.filter((item) => item.method === 'POST' && item.path === '/api/tutor/sessions')
  assert.equal(tutorCreate.length, 1, 'default header Tutor action should create one isolated fixture session')
  assert.equal(tutorCreate[0].body.context_type, 'resource_help')
  assert.equal(tutorCreate[0].body.resource_id, 'resource-lecture')
  assert.equal(tutorCreate[0].body.learner_id, 'learner-1')
  evidence.interactionChecks.push({ scenario: 'default-reader-header-slots', tutorSession: tutorCreate[0], download: '/api/resources/file/resource-lecture' })
  await page.locator('.tutor-panel .tutor-close').click()
  await page.locator('.tutor-panel').waitFor({ state: 'hidden' })

  const selectedShelfItem = page.locator('.resources-page .resource-item').filter({ hasText: '复习清单' })
  await selectedShelfItem.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-checklist')
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('复习清单'))
  assert.ok(await selectedShelfItem.evaluate((node) => node.classList.contains('is-active')),
    'selected resource shelf item should receive its active state')
  await assertSelectedResourceVisualState(page, 'resources-selected-shelf-card-state',
    '.resources-page .resource-item.is-active', '.resources-page .resource-item:not(.is-active)')
  assert.ok((await libraryReader.locator('.resource-content h1').innerText()).includes('复习清单'),
    'resource shelf selection should update the visible reader body')
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-click')
  await page.mouse.move(12, 12)
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-rest')
  await selectedShelfItem.hover()
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-hover')
  await capture(page, 'desktop-resources-selected-checklist')
  const shelfDownloadPromise = page.waitForEvent('popup')
  await libraryReader.locator('.reader-header .download-button').click()
  const shelfDownload = await shelfDownloadPromise
  await shelfDownload.waitForLoadState('domcontentloaded')
  assert.equal(new URL(shelfDownload.url()).pathname, '/api/resources/file/resource-checklist',
    'resource shelf selection should bind the reader download to the selected resource')
  assert.ok((await shelfDownload.locator('body').innerText()).includes('Isolated fixture download for resource-checklist'),
    'selected resource download should resolve through its matching local fixture')
  evidence.interactionChecks.push({ scenario: 'resources-shelf-selection-download', resourceId: 'resource-checklist', url: shelfDownload.url(), method: 'GET' })
  await shelfDownload.close()

  const resourceListRequestsBeforeRefresh = state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method === 'GET').length
  await page.locator('.resources-page .refresh-button').click()
  await waitForFixture(
    () => state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method === 'GET').length === resourceListRequestsBeforeRefresh + 1,
    'Resources view refresh GET',
  )
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('复习清单'))
  assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-checklist',
    'resource refresh should retain the selected resource route')
  assert.equal(state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method !== 'GET').length, 0,
    'resource refresh should remain read-only')
  evidence.interactionChecks.push({ scenario: 'resources-refresh', endpoint: '/api/resource-library/learner-1', method: 'GET' })

  const firstShelfItem = page.locator('.resources-page .resource-item').first()
  const firstShelfStyleBefore = await firstShelfItem.evaluate((node) => {
    const style = getComputedStyle(node)
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, boxShadow: style.boxShadow, borderColor: style.borderTopColor }
  })
  await page.locator('.resources-page .focus-button').focus()
  await page.keyboard.press('Tab')
  const keyboardFocus = await page.evaluate(() => {
    const node = document.activeElement
    if (!node) return null
    const style = getComputedStyle(node)
    return {
      selector: node.className,
      resourceButton: node.matches('.resources-page .resource-item'),
      focusVisible: node.matches(':focus-visible'),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
      borderColor: style.borderTopColor,
    }
  })
  assert.equal(keyboardFocus?.resourceButton, true, 'Tab from the toolbar should reach the resource shelf button')
  assert.equal(keyboardFocus.focusVisible, true, 'resource shelf button should expose keyboard focus-visible state')
  assert.ok((keyboardFocus.outlineStyle !== 'none' && keyboardFocus.outlineWidth !== '0px')
    || keyboardFocus.boxShadow !== firstShelfStyleBefore.boxShadow
    || keyboardFocus.borderColor !== firstShelfStyleBefore.borderColor,
  'keyboard focus should have a visible indicator on the resource shelf button')
  evidence.interactionChecks.push({ scenario: 'resources-keyboard-focus', ...keyboardFocus, before: firstShelfStyleBefore })

  const longShelfItem = page.locator('.resources-page .resource-item').filter({ hasText: '多阶段知识迁移与证据核验实操指南资源类型' })
  await longShelfItem.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-guide')
  await page.waitForFunction((expectedTitle) => document.querySelector('.resources-page .resource-content h1')?.textContent.includes(expectedTitle), longResourceType)
  assert.ok(await longShelfItem.evaluate((node) => node.classList.contains('is-active')),
    'long document selection should remain visible in the resource shelf')

  await page.setViewportSize({ width: 1331, height: 871 })
  await setResourcesSidebar(page, true)
  await page.waitForTimeout(100)
  await assertResourcesGeometry(page, 'resources-1331x871-collapsed')
  assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed')), true,
    'Resources view should preserve its layout with the sidebar collapsed')
  await assertResourcesControls(page, 'resources-1331x871-collapsed', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
    '.resources-page .resource-feedback-button',
    '.resources-page .tutor-trigger',
  ])
  await capture(page, 'desktop-resources-sidebar-collapsed')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await page.waitForTimeout(100)
  const resourcesMobile = await assertResourcesGeometry(page, 'resources-390x844')
  for (const viewport of [{ width: 390, height: 844 }, { width: 375, height: 667 }]) {
    await page.setViewportSize(viewport)
    for (const collapsed of [false, true]) {
      await page.evaluate(() => {
        document.querySelector('.content-area')?.scrollTo(0, 0)
        document.querySelector('.resources-page')?.scrollTo(0, 0)
      })
      await setResourcesSidebar(page, collapsed)
      const label = `resources-mobile-nav-${viewport.width}x${viewport.height}-${collapsed ? 'collapsed' : 'expanded'}`
      await assertResourcesMobileSidebarGeometry(page, label, collapsed)
      await capture(page, label)
    }
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await setResourcesSidebar(page, true)
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await page.waitForTimeout(50)
  await assertResourcesControls(page, 'resources-390x844-toolbar', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
  ])
  const shelfScroll = await page.locator('.resources-page .resource-shelf').evaluate((node) => {
    const before = node.scrollLeft
    const maxScroll = node.scrollWidth - node.clientWidth
    const overflowX = getComputedStyle(node).overflowX
    node.scrollTo({ left: maxScroll, behavior: 'instant' })
    const lastResource = [...node.querySelectorAll('.resource-item')].at(-1)
    const shelfRect = node.getBoundingClientRect()
    const lastRect = lastResource?.getBoundingClientRect()
    return {
      before,
      after: node.scrollLeft,
      maxScroll,
      overflowX,
      lastResourceVisible: Boolean(lastRect && lastRect.right <= shelfRect.right + 1 && lastRect.left >= shelfRect.left - 1),
    }
  })
  assert.ok(['auto', 'scroll'].includes(shelfScroll.overflowX) && shelfScroll.maxScroll > 0 && shelfScroll.after > shelfScroll.before,
    'mobile resource shelf should remain horizontally scrollable: ' + JSON.stringify(shelfScroll))
  assert.equal(shelfScroll.lastResourceVisible, true, 'horizontal shelf scrolling should expose the final resource card')
  evidence.scrollChecks.push({ label: 'resources-mobile-horizontal-shelf', ...shelfScroll })
  await page.locator('.resources-page .reading-stage .resource-content h1').scrollIntoViewIfNeeded()
  await page.locator('.resources-page .reading-stage .resource-content h1').waitFor({ state: 'visible' })
  await assertContrast(page, 'resources-mobile-reader')
  await capture(page, 'mobile-resources-reader')
  evidence.layoutChecks.push({ label: 'resources-mobile-reader-visible', viewport: resourcesMobile.viewport, title: await page.locator('.resources-page .reading-stage .resource-content h1').innerText() })

  await page.setViewportSize(baseViewport)
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await setResourcesSidebar(page, false)
  await page.waitForTimeout(100)
  await page.locator('.resources-page .focus-button').click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('focus') === '1')
  await page.locator('.resources-layout.is-focus-mode .focus-resource-switcher').waitFor({ state: 'visible' })
  await assertResourcesGeometry(page, 'resources-focus-1393x871')
  await assertResourcesControls(page, 'resources-focus-exit', ['.resources-page .focus-exit'])
  await assertContrast(page, 'resources-focus-mode')
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
    document.querySelector('.resources-page .resource-content')?.scrollTo(0, 0)
  })
  await capture(page, 'desktop-resources-focus')

  const focusSwitcher = page.locator('.resources-page .focus-resource-switcher')
  const lectureSwitch = focusSwitcher.getByRole('button', { name: /讲义/ })
  assert.equal(await lectureSwitch.getAttribute('aria-pressed'), 'false', 'focus switcher should identify the currently unselected document')
  await lectureSwitch.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-lecture')
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('讲义'))
  assert.equal(await lectureSwitch.getAttribute('aria-pressed'), 'true', 'focus switcher should mark the selected document')
  await assertSelectedResourceVisualState(page, 'resources-focus-switcher-state',
    '.resources-page .focus-resource-switcher button.is-active', '.resources-page .focus-resource-switcher button:not(.is-active)')
  evidence.interactionChecks.push({ scenario: 'resources-focus-switcher', resourceId: 'resource-lecture' })
  await capture(page, 'desktop-resources-focus-switched')
  await page.locator('.resources-page .focus-exit').click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('focus') !== '1')
  assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-lecture', 'leaving focus mode should preserve the selected resource')
  // The existing App branch remount reloads the library asynchronously.
  await page.waitForFunction(() => document.querySelector('.app-shell .learning-workspace .resource-content h1')?.textContent.includes('讲义'))
  await assertResourcesGeometry(page, 'resources-focus-exited')
  evidence.interactionChecks.push({ scenario: 'resources-focus-enter-exit', selectedResourceId: 'resource-lecture' })
  await assertNoExternalOrUnexpected('learning-mode-route')
  assert.deepEqual(state.writes.map((item) => ({ method: item.method, path: item.path })), [
    { method: 'POST', path: '/api/tutor/sessions' },
  ], 'Resources view UI checks should not produce business writes beyond the isolated Tutor session')
  await page.close()

  const historyPage = await newPage(browser, base, 'completed')
  await assertNoLocalHistoryAction(historyPage, 'learning-history-route')
  await historyPage.locator('.topbar .topbar-action').filter({ hasText: '学习历史' }).click()
  await assertRouteFixtureReady(historyPage, '/learning/history')
  evidence.interactionChecks.push({ scenario: 'completed', route: historyPage.url(), action: 'learning-history' })
  await assertNoExternalOrUnexpected('learning-history-route')
  await historyPage.close()
}

async function testClaimAndAppend(browser, base) {
  const claimPage = await newPage(browser, base, 'claim-pending')
  await claimPage.getByRole('button', { name: '查看审核报告' }).first().click()
  await claimPage.getByRole('heading', { name: '资源 Claim 审核报告' }).waitFor()
  assert.ok((await claimPage.locator('.claim-report-dialog').innerText()).includes('验收事实陈述'), 'claim dialog should retain its report content')
  await capture(claimPage, 'desktop-claim-report')
  await claimPage.getByRole('button', { name: '确认发布' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.includes('claim-publication-decision')), 'claim decision')
  assert.equal(state.writes.filter((item) => item.path.includes('claim-publication-decision')).length, 1, 'claim decision should submit once')
  assert.deepEqual(state.lastClaimDecision, { resource_id: 'resource-guide', body: { publish: true } })
  evidence.interactionChecks.push({ scenario: 'claim-report', decision: state.lastClaimDecision })
  await assertNoExternalOrUnexpected('claim-report')
  await claimPage.close()

  const retainPage = await newPage(browser, base, 'claim-pending')
  await retainPage.getByRole('button', { name: '查看审核报告' }).first().click()
  await retainPage.getByRole('heading', { name: '资源 Claim 审核报告' }).waitFor()
  await retainPage.getByRole('button', { name: '暂不发布' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.includes('claim-publication-decision')), 'claim retain decision')
  assert.deepEqual(state.lastClaimDecision, { resource_id: 'resource-guide', body: { publish: false } })
  evidence.interactionChecks.push({ scenario: 'claim-report-retain', decision: state.lastClaimDecision })
  await assertNoExternalOrUnexpected('claim-report-retain')
  await retainPage.close()

  const splitPage = await newPage(browser, base, 'completed')
  await appendTextTypes(splitPage, true, ['复习清单', '案例分析'], 'desktop-append-dialog')
  await waitForFixture(() => state.writes.filter((item) => item.path.endsWith('/continuations')).length === 2, 'Claim-enabled append split')
  const splitWrites = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(splitWrites.length, 2, 'Claim-enabled append should split each resource type into its own request')
  assert.ok(splitWrites.every((item) => item.body.resource_types.length === 1), 'Claim-enabled append should submit one resource type per request')
  assert.deepEqual(new Set(splitWrites.map((item) => item.body.resource_types[0])), new Set(['复习清单', '案例分析']),
    'Claim-enabled append should preserve both selected resource types; independent parallel request arrival order is not significant')
  assert.ok(splitWrites.every((item) => item.body.include_claim_check === true && item.body.source_run_id === 'run-main'))
  evidence.interactionChecks.push({ scenario: 'append-claim-enabled', writes: splitWrites })
  await assertNoExternalOrUnexpected('append-claim-enabled')
  await splitPage.close()

  const mergedPage = await newPage(browser, base, 'completed')
  await appendTextTypes(mergedPage, false, ['复习清单', '案例分析'])
  await waitForFixture(() => state.writes.filter((item) => item.path.endsWith('/continuations')).length === 1, 'Claim-disabled append merge')
  const mergedWrites = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(mergedWrites.length, 1, 'Claim-disabled append should submit one combined continuation')
  assert.deepEqual(mergedWrites[0].body.resource_types, ['复习清单', '案例分析'])
  assert.equal(mergedWrites[0].body.include_claim_check, false)
  evidence.interactionChecks.push({ scenario: 'append-claim-disabled', writes: mergedWrites })
  await assertNoExternalOrUnexpected('append-claim-disabled')
  await mergedPage.close()
}

async function testRetriesAndCourseware(browser, base) {
  const partialPage = await newPage(browser, base, 'partial')
  await partialPage.getByRole('button', { name: '重新生成此资源' }).first().click()
  await partialPage.waitForFunction(() => document.querySelector('.el-message__content')?.textContent.includes('已在当前批次重新生成'))
  const itemRetry = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(itemRetry.length, 1)
  assert.deepEqual(itemRetry[0].body.resource_types, ['实操指南'])
  assert.equal(itemRetry[0].body.replace_existing_types, true)
  await assertNoExternalOrUnexpected('single-resource-retry')
  await partialPage.close()

  const retryPendingPage = await newPage(browser, base, 'partial')
  await retryPendingPage.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: /重新生成失败资源/ }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/continuations')), 'batch retry of pending resources')
  const pendingRetry = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(pendingRetry.length, 1)
  assert.equal(pendingRetry[0].body.replace_existing_types, true)
  assert.deepEqual(pendingRetry[0].body.resource_types, ['实操指南'])
  evidence.interactionChecks.push({ scenario: 'pending-resource-batch-retry', write: pendingRetry[0] })
  await assertNoExternalOrUnexpected('pending-resource-batch-retry')
  await retryPendingPage.close()

  const batchFailurePage = await newPage(browser, base, 'failed')
  await batchFailurePage.locator('.resources-panel > .panel-title .task-actions').getByRole('button', { name: '重新生成', exact: true }).click()
  await batchFailurePage.waitForFunction(() => document.querySelector('.el-message__content')?.textContent.includes('已在原资源批次中重新发起'))
  const batchRetry = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(batchRetry.length, 1)
  assert.equal(batchRetry[0].body.source_run_id, 'run-main')
  assert.deepEqual(batchRetry[0].body.resource_types, ['讲义', '实操指南', '分阶测试题'])
  evidence.interactionChecks.push({ scenario: 'failed-batch-retry', write: batchRetry[0] })
  await assertNoExternalOrUnexpected('failed-batch-retry')
  await batchFailurePage.close()

  const coursewarePage = await newPage(browser, base, 'completed')
  await openAppendDialog(coursewarePage, 'HTML 互动课件')
  assert.ok(await coursewarePage.locator('.source-list .el-checkbox').count() >= 2, 'courseware dialog should offer published practical/checklist sources')
  const sourceNames = await coursewarePage.locator('.source-list .el-checkbox').allInnerTexts()
  assert.ok(sourceNames.every((text) => /实操指南|复习清单/.test(text)), 'courseware source selection must exclude non-eligible assets')
  const sourceDialog = coursewarePage.getByRole('dialog').filter({ hasText: '创建互动课件' })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const dialogMetrics = await sourceDialog.locator('.el-dialog').evaluate((dialog) => {
    const rect = dialog.getBoundingClientRect()
    const body = dialog.querySelector('.el-dialog__body')
    const footer = dialog.querySelector('.el-dialog__footer')
    const primary = footer?.querySelector('.el-button--primary')
    const bodyRect = body?.getBoundingClientRect()
    return {
      dialog: { top: rect.top, bottom: rect.bottom, height: rect.height, maxHeight: getComputedStyle(dialog).maxHeight },
      body: body && bodyRect ? { top: bodyRect.top, bottom: bodyRect.bottom, height: bodyRect.height, scrollHeight: body.scrollHeight, clientHeight: body.clientHeight, overflowY: getComputedStyle(body).overflowY } : null,
      footer: footer ? { top: footer.getBoundingClientRect().top, bottom: footer.getBoundingClientRect().bottom } : null,
      primaryHeight: primary?.getBoundingClientRect().height ?? 0,
      viewportHeight: innerHeight,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-source-dialog', ...dialogMetrics })
  await capture(coursewarePage, 'desktop-courseware-source-dialog')
  assert.ok(dialogMetrics.dialog.top >= -1 && dialogMetrics.dialog.bottom <= dialogMetrics.viewportHeight + 1, 'courseware source dialog must stay within viewport: ' + JSON.stringify(dialogMetrics))
  assert.notEqual(dialogMetrics.dialog.maxHeight, 'none', 'courseware source dialog must cap its height')
  assert.ok(dialogMetrics.body && dialogMetrics.body.overflowY === 'auto', 'courseware source dialog body should be internally scrollable')
  assert.ok(dialogMetrics.body.top >= dialogMetrics.dialog.top - 1 && dialogMetrics.body.bottom <= dialogMetrics.dialog.bottom + 1, 'courseware source body should stay inside its dialog')
  assert.ok(dialogMetrics.primaryHeight >= 44, 'courseware source dialog primary action should be at least 44px high')
  await assertContrast(coursewarePage, 'courseware-source-dialog')
  await coursewarePage.setViewportSize({ width: 390, height: 844 })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const mobileSourceMetrics = await sourceDialog.locator('.el-dialog').evaluate((dialog) => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height }
    }
    const body = dialog.querySelector('.el-dialog__body')
    const footer = dialog.querySelector('.el-dialog__footer')
    const primary = footer?.querySelector('.el-button--primary')
    const controls = [...dialog.querySelectorAll('.preference-grid .el-input, .preference-grid .el-input-number, .source-list .el-checkbox, .el-dialog__footer button')]
      .filter((node) => node.getClientRects().length)
      .map((node) => ({ text: node.innerText?.trim() || node.getAttribute('aria-label') || node.tagName, ...rect(node) }))
    return {
      viewport: { width: innerWidth, height: innerHeight },
      dialog: { ...rect(dialog), scrollWidth: dialog.scrollWidth, clientWidth: dialog.clientWidth },
      body: body && { ...rect(body), scrollHeight: body.scrollHeight, clientHeight: body.clientHeight, scrollWidth: body.scrollWidth, clientWidth: body.clientWidth },
      footer: footer && rect(footer),
      primaryHeight: primary?.getBoundingClientRect().height ?? 0,
      controls,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-source-dialog-mobile', ...mobileSourceMetrics })
  assert.ok(mobileSourceMetrics.dialog.left >= -1 && mobileSourceMetrics.dialog.right <= 391, 'mobile source dialog should fit viewport: ' + JSON.stringify(mobileSourceMetrics))
  assert.equal(mobileSourceMetrics.dialog.scrollWidth, mobileSourceMetrics.dialog.clientWidth, 'mobile source dialog should not overflow horizontally')
  assert.ok(mobileSourceMetrics.body && mobileSourceMetrics.body.scrollWidth <= mobileSourceMetrics.body.clientWidth + 1, 'mobile source dialog body should not overflow horizontally')
  assert.ok(mobileSourceMetrics.footer && mobileSourceMetrics.footer.bottom <= 845, 'mobile source dialog footer should remain reachable')
  assert.ok(mobileSourceMetrics.primaryHeight >= 44, 'mobile source dialog primary action should remain at least 44px high')
  for (const control of mobileSourceMetrics.controls) {
    assert.ok(control.left >= mobileSourceMetrics.dialog.left - 1 && control.right <= mobileSourceMetrics.dialog.right + 1, 'mobile source dialog control should stay inside dialog: ' + JSON.stringify(control))
  }
  await sourceDialog.locator('.el-dialog__body').evaluate((body) => { body.scrollTop = body.scrollHeight })
  const mobileFooterAfterScroll = await sourceDialog.locator('.el-dialog__footer').boundingBox()
  assert.ok(mobileFooterAfterScroll && mobileFooterAfterScroll.y + mobileFooterAfterScroll.height <= 845, 'mobile source dialog footer should remain visible after reading to the end')
  evidence.layoutChecks.push({ label: 'courseware-source-dialog-mobile-footer', bodyScrollTop: await sourceDialog.locator('.el-dialog__body').evaluate((body) => body.scrollTop), footer: mobileFooterAfterScroll })
  await capture(coursewarePage, 'mobile-courseware-source-dialog')
  await coursewarePage.setViewportSize({ width: 1393, height: 871 })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const learningGoalField = coursewarePage.locator('.preference-grid label').first()
  const learningGoalInput = learningGoalField.locator('input')
  await assertWrappedFieldFocus(coursewarePage, 'courseware-source-learning-goal', learningGoalInput, learningGoalField.locator('.el-input__wrapper'), 'focus-courseware-source-learning-goal', { keyboardFocus: false })
  await learningGoalInput.fill('理解每个学习步骤')
  const expectedDurationField = coursewarePage.locator('.preference-grid label').nth(1)
  await assertWrappedFieldFocus(coursewarePage, 'courseware-source-expected-duration', expectedDurationField.locator('.el-input-number input'), expectedDurationField.locator('.el-input-number .el-input__wrapper'), null, { keyboardFocus: false })
  await coursewarePage.getByRole('button', { name: /生成互动版/ }).click()
  await coursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  const createWrite = state.writes.find((item) => item.path === '/api/resources/courseware/jobs/batch')
  assert.ok(createWrite, 'courseware append should create a batch job')
  assert.equal(createWrite.body.learner_id, 'learner-1')
  assert.deepEqual(createWrite.body.resource_ids, ['resource-guide', 'resource-checklist'])
  assert.equal(createWrite.body.learning_goal, '理解每个学习步骤')
  assert.equal(createWrite.body.expected_duration_minutes, 30)
  assert.equal(new URL(coursewarePage.url()).pathname, '/generate', 'embedded courseware should remain in the generation workspace')
  await geometry(coursewarePage, 'courseware-embedded', false)
  await capture(coursewarePage, 'desktop-courseware-embedded')
  evidence.interactionChecks.push({ scenario: 'courseware-create', write: createWrite, route: coursewarePage.url() })
  await assertNoExternalOrUnexpected('courseware-create')
  await coursewarePage.close()

  const longCoursewarePage = await newPage(browser, base, 'courseware-long')
  await longCoursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  await longCoursewarePage.waitForFunction(() => {
    const process = document.querySelector('.generation-grid > .process-panel')
    const details = document.querySelector('.details-scroll')
    return process?.getAttribute('role') === 'region'
      && process.getAttribute('aria-label') === '课件生成过程'
      && process.getAttribute('tabindex') === '0'
      && details?.getAttribute('role') === 'region'
      && details.getAttribute('aria-label') === '课件过程详情'
      && details.getAttribute('tabindex') === '0'
      && details.scrollHeight > details.clientHeight
  })
  const coursewareDetails = longCoursewarePage.locator('.details-scroll')
  const coursewareGeometry = await longCoursewarePage.evaluate(() => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, height: value.height, width: value.width }
    }
    const processPanel = document.querySelector('.generation-grid > .process-panel')
    const detailsPanel = document.querySelector('.details-panel')
    const details = document.querySelector('.details-scroll')
    const area = document.querySelector('.content-area')
    const processRegion = processPanel
    const stageLabels = [...document.querySelectorAll('.workflow-snake-copy strong, .workflow-snake-copy small')].map((node) => {
      const style = getComputedStyle(node)
      const bounds = node.getBoundingClientRect()
      const step = node.closest('.workflow-snake-step')?.getBoundingClientRect()
      return {
        text: node.textContent.trim(),
        tag: node.tagName.toLowerCase(),
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        textOverflow: style.textOverflow,
        whiteSpace: style.whiteSpace,
        lineClamp: style.lineClamp || style.webkitLineClamp || 'none',
        maxHeight: style.maxHeight,
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        top: bounds.top,
        bottom: bounds.bottom,
        stepTop: step?.top ?? null,
        stepBottom: step?.bottom ?? null,
      }
    })
    return {
      fit: document.querySelector('.generate-page')?.classList.contains('is-fit-layout') || false,
      processTitle: rect(processPanel.querySelector('.panel-title')),
      detailsTitle: rect(detailsPanel.querySelector('.panel-title')),
      processPanel: rect(processPanel),
      detailsPanel: rect(detailsPanel),
      processRegion: { ...rect(processRegion), scrollTop: processRegion.scrollTop, scrollHeight: processRegion.scrollHeight, clientHeight: processRegion.clientHeight, scrollWidth: processRegion.scrollWidth, clientWidth: processRegion.clientWidth },
      stageLabels,
      details: { ...rect(details), scrollTop: details.scrollTop, scrollHeight: details.scrollHeight, clientHeight: details.clientHeight, scrollWidth: details.scrollWidth, clientWidth: details.clientWidth },
      outer: { document: document.documentElement.scrollTop, content: area?.scrollTop ?? null, root: document.querySelector('.generate-page')?.scrollTop ?? null },
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-long-initial', ...coursewareGeometry })
  await capture(longCoursewarePage, 'desktop-courseware-long-top')
  assert.ok(Math.abs(coursewareGeometry.processTitle.top - coursewareGeometry.detailsTitle.top) <= 1, 'courseware pane headings should align within 1px: ' + JSON.stringify({ processTitle: coursewareGeometry.processTitle, detailsTitle: coursewareGeometry.detailsTitle }))
  assert.ok(Math.abs(coursewareGeometry.processTitle.bottom - coursewareGeometry.detailsTitle.bottom) <= 1, 'courseware pane heading bottoms should align within 1px: ' + JSON.stringify({ processTitle: coursewareGeometry.processTitle, detailsTitle: coursewareGeometry.detailsTitle }))
  assert.equal(coursewareGeometry.processRegion.scrollWidth, coursewareGeometry.processRegion.clientWidth, 'courseware process region should not overflow horizontally')
  assert.ok(coursewareGeometry.stageLabels.length >= 24, 'courseware snake should render every stage label and description')
  for (const label of coursewareGeometry.stageLabels) {
    assert.ok(label.text, 'courseware stage labels and descriptions should contain readable text')
    assert.equal(label.whiteSpace, 'normal', 'courseware stage text should wrap instead of being forced onto one line: ' + JSON.stringify(label))
    assert.equal(label.textOverflow, 'clip', 'courseware stage text should not use ellipsis: ' + JSON.stringify(label))
    assert.ok(!['hidden', 'clip'].includes(label.overflowX) && !['hidden', 'clip'].includes(label.overflowY), 'courseware stage text should not be clipped by its own box: ' + JSON.stringify(label))
    assert.ok(['none', 'normal', '0', ''].includes(label.lineClamp), 'courseware stage text should not use line clamping: ' + JSON.stringify(label))
    assert.ok(label.maxHeight === 'none' || Number.parseFloat(label.maxHeight) >= label.scrollHeight - 1, 'courseware stage text should not have a restrictive max-height: ' + JSON.stringify(label))
    assert.ok(label.scrollWidth <= label.clientWidth + 1 && label.scrollHeight <= label.clientHeight + 1, 'courseware stage label must fit its rendered box without hidden overflow: ' + JSON.stringify(label))
    assert.ok(label.top >= label.stepTop - 1 && label.bottom <= label.stepBottom + 1, 'courseware stage text should remain inside its node card: ' + JSON.stringify(label))
  }
  const coursewareProcess = longCoursewarePage.locator('.generation-grid > .process-panel')
  await coursewareProcess.evaluate((node) => { node.scrollTop = 0; node.focus() })
  const coursewareProcessFocus = await coursewareProcess.evaluate((node) => ({
    active: document.activeElement === node,
    focusVisible: node.matches(':focus-visible'),
    outline: getComputedStyle(node).outlineStyle,
    outlineWidth: getComputedStyle(node).outlineWidth,
    scrollHeight: node.scrollHeight,
    clientHeight: node.clientHeight,
    scrollTop: node.scrollTop,
  }))
  assert.equal(coursewareProcessFocus.active, true, 'courseware process region should receive keyboard focus')
  assert.ok(coursewareProcessFocus.focusVisible || (coursewareProcessFocus.outline !== 'none' && coursewareProcessFocus.outlineWidth !== '0px'), 'courseware process region should show a focus indicator')
  const processScrollEvidence = { before: coursewareProcessFocus, afterProgram: coursewareProcessFocus.scrollTop, afterKeyboard: coursewareProcessFocus.scrollTop, afterWheel: coursewareProcessFocus.scrollTop, outerBefore: coursewareGeometry.outer, outerAfter: coursewareGeometry.outer, titleAfterWheel: coursewareGeometry.processTitle, footerActions: [] }
  if (coursewareProcessFocus.scrollHeight > coursewareProcessFocus.clientHeight) {
    await coursewareProcess.evaluate((node) => { node.scrollTop = Math.min(120, node.scrollHeight) })
    processScrollEvidence.afterProgram = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterProgram > 0, 'courseware process region should support programmatic scrolling when its content overflows')
    await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
    await longCoursewarePage.keyboard.press('PageDown')
    await longCoursewarePage.waitForTimeout(80)
    processScrollEvidence.afterKeyboard = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterKeyboard > 0, 'PageDown should scroll an overflowing courseware process region')
    await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
    const processBox = await coursewareProcess.boundingBox()
    await longCoursewarePage.mouse.move(processBox.x + processBox.width / 2, processBox.y + processBox.height / 2)
    await longCoursewarePage.mouse.wheel(0, 280)
    await longCoursewarePage.waitForTimeout(80)
    processScrollEvidence.afterWheel = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterWheel > 0, 'wheel should scroll an overflowing courseware process region')
    processScrollEvidence.outerAfter = await longCoursewarePage.evaluate(() => ({
      document: document.documentElement.scrollTop,
      content: document.querySelector('.content-area')?.scrollTop ?? null,
      root: document.querySelector('.generate-page')?.scrollTop ?? null,
    }))
    processScrollEvidence.titleAfterWheel = await longCoursewarePage.locator('.process-panel > .panel-title').boundingBox()
    assert.deepEqual(processScrollEvidence.outerAfter, processScrollEvidence.outerBefore, 'courseware process inner wheel should not move outer page')
    assert.ok(Math.abs(processScrollEvidence.titleAfterWheel.y - coursewareGeometry.processTitle.top) <= 1, 'courseware process title should stay fixed while its pane scrolls')
    await coursewareProcess.evaluate((node) => { node.scrollTop = node.scrollHeight })
  }
  const processActions = await longCoursewarePage.locator('.process-panel .process-actions button').evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect()
    const panel = node.closest('.process-panel').getBoundingClientRect()
    return { text: node.innerText.trim(), top: rect.top, bottom: rect.bottom, height: rect.height, visible: rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden', insidePanel: rect.top >= panel.top - 1 && rect.bottom <= panel.bottom + 1 }
  }))
  assert.ok(processActions.length > 0, 'courseware process footer actions should remain available')
  for (const action of processActions) {
    assert.ok(action.visible && action.insidePanel, 'courseware process footer action should be reachable within its pane: ' + JSON.stringify(action))
    assert.ok(action.height >= 44, 'courseware process footer action should meet the 44px target: ' + JSON.stringify(action))
  }
  processScrollEvidence.footerActions = processActions
  evidence.scrollChecks.push({ label: 'courseware-process-pane', ...processScrollEvidence })
  await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
  assert.ok(coursewareGeometry.details.scrollHeight > coursewareGeometry.details.clientHeight, 'long courseware fixture should overflow the details region')
  assert.ok(coursewareGeometry.details.height >= 120, 'courseware details region should remain usable')
  assert.equal(coursewareGeometry.details.scrollWidth, coursewareGeometry.details.clientWidth, 'long courseware details should not overflow horizontally')
  await coursewareDetails.evaluate((node) => { node.scrollTop = 0; node.focus() })
  const coursewareFocus = await coursewareDetails.evaluate((node) => ({
    active: document.activeElement === node,
    focusVisible: node.matches(':focus-visible'),
    outline: getComputedStyle(node).outlineStyle,
    outlineWidth: getComputedStyle(node).outlineWidth,
  }))
  assert.equal(coursewareFocus.active, true, 'courseware details region should be keyboard focusable')
  assert.ok(coursewareFocus.focusVisible || (coursewareFocus.outline !== 'none' && coursewareFocus.outlineWidth !== '0px'), 'courseware details focus indicator should be visible')
  await longCoursewarePage.keyboard.press('PageDown')
  await longCoursewarePage.waitForTimeout(80)
  const coursewareAfterKeyboard = await coursewareDetails.evaluate((node) => node.scrollTop)
  assert.ok(coursewareAfterKeyboard > 0, 'PageDown should scroll courseware details internally')
  await coursewareDetails.evaluate((node) => { node.scrollTop = 0 })
  const detailsBox = await coursewareDetails.boundingBox()
  await longCoursewarePage.mouse.move(detailsBox.x + detailsBox.width / 2, detailsBox.y + detailsBox.height / 2)
  await longCoursewarePage.mouse.wheel(0, 360)
  await longCoursewarePage.waitForTimeout(80)
  const scrollAfterWheel = await coursewareDetails.evaluate((node) => node.scrollTop)
  const outerAfterWheel = await longCoursewarePage.evaluate(() => ({
    document: document.documentElement.scrollTop,
    content: document.querySelector('.content-area')?.scrollTop ?? null,
    root: document.querySelector('.generate-page')?.scrollTop ?? null,
  }))
  const titleAfterWheel = await longCoursewarePage.locator('.details-panel .panel-title').boundingBox()
  assert.ok(scrollAfterWheel > 0, 'wheel should scroll courseware details internally')
  assert.deepEqual(outerAfterWheel, coursewareGeometry.outer, 'courseware inner wheel should not move outer page')
  assert.ok(Math.abs(titleAfterWheel.y - coursewareGeometry.detailsTitle.top) <= 1, 'courseware detail title should stay fixed while details scroll')
  await coursewareDetails.evaluate((node) => { node.scrollTop = node.scrollHeight })
  await longCoursewarePage.waitForTimeout(80)
  const finalWarning = longCoursewarePage.getByText('长课件警告 16', { exact: true })
  const finalWarningRect = await finalWarning.boundingBox()
  const detailsRect = await coursewareDetails.boundingBox()
  assert.ok(finalWarningRect && finalWarningRect.y >= detailsRect.y - 1 && finalWarningRect.y + finalWarningRect.height <= detailsRect.y + detailsRect.height + 1, 'last courseware warning should be reachable inside details region')
  evidence.scrollChecks.push({ label: 'courseware-long', before: coursewareGeometry.details, afterKeyboard: coursewareAfterKeyboard, afterWheel: scrollAfterWheel, outerBefore: coursewareGeometry.outer, outerAfter: outerAfterWheel, coursewareFocus, finalWarningRect, detailsRect })
  await capture(longCoursewarePage, 'desktop-courseware-long')
  await assertContrast(longCoursewarePage, 'courseware-long')
  await longCoursewarePage.setViewportSize({ width: 390, height: 844 })
  await longCoursewarePage.waitForTimeout(120)
  const mobileCoursewareMetrics = await longCoursewarePage.evaluate(() => {
    const area = document.querySelector('.content-area')
    const root = document.querySelector('.generate-page')
    const labels = [...document.querySelectorAll('.workflow-snake-copy strong, .workflow-snake-copy small')].map((node) => {
      const style = getComputedStyle(node)
      return {
        text: node.textContent.trim(),
        whiteSpace: style.whiteSpace,
        textOverflow: style.textOverflow,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        lineClamp: style.lineClamp || style.webkitLineClamp || 'none',
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
      }
    })
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      fit: root?.classList.contains('is-fit-layout') || false,
      area: area && { scrollTop: area.scrollTop, scrollHeight: area.scrollHeight, clientHeight: area.clientHeight, scrollWidth: area.scrollWidth, clientWidth: area.clientWidth },
      labels,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-long-mobile', ...mobileCoursewareMetrics })
  assert.ok(mobileCoursewareMetrics.document.scrollWidth <= mobileCoursewareMetrics.document.clientWidth + 1, 'mobile courseware page should not overflow horizontally: ' + JSON.stringify({ document: mobileCoursewareMetrics.document }))
  assert.ok(mobileCoursewareMetrics.area && mobileCoursewareMetrics.area.scrollWidth <= mobileCoursewareMetrics.area.clientWidth + 1, 'mobile courseware content should not overflow horizontally: ' + JSON.stringify(mobileCoursewareMetrics.area))
  assert.ok(mobileCoursewareMetrics.area.scrollHeight > mobileCoursewareMetrics.area.clientHeight, 'long courseware content should remain naturally scrollable on mobile')
  assert.equal(mobileCoursewareMetrics.labels.length, coursewareGeometry.stageLabels.length, 'mobile viewport should preserve every workflow stage label and description')
  for (const label of mobileCoursewareMetrics.labels) {
    assert.ok(label.text, 'mobile courseware stage labels should remain readable')
    assert.equal(label.whiteSpace, 'normal', 'mobile courseware stage text should wrap naturally')
    assert.equal(label.textOverflow, 'clip', 'mobile courseware stage text should not use ellipsis')
    assert.ok(!['hidden', 'clip'].includes(label.overflowX) && !['hidden', 'clip'].includes(label.overflowY), 'mobile courseware stage text should not be clipped')
    assert.ok(['none', 'normal', '0', ''].includes(label.lineClamp), 'mobile courseware stage text should not use line clamping')
    assert.ok(label.scrollWidth <= label.clientWidth + 1 && label.scrollHeight <= label.clientHeight + 1, 'mobile courseware stage text should fit its rendered box')
  }
  await capture(longCoursewarePage, 'mobile-courseware-long')
  await longCoursewarePage.locator('.content-area').evaluate((node) => { node.scrollTop = Math.min(240, node.scrollHeight) })
  const mobileCoursewareAfterScroll = await longCoursewarePage.locator('.content-area').evaluate((node) => node.scrollTop)
  assert.ok(mobileCoursewareAfterScroll > 0, 'mobile courseware page should permit natural vertical reading scroll')
  evidence.scrollChecks.push({ label: 'courseware-long-mobile-natural', before: mobileCoursewareMetrics.area.scrollTop, afterProgram: mobileCoursewareAfterScroll, area: mobileCoursewareMetrics.area })
  await assertNoExternalOrUnexpected('courseware-long')
  await longCoursewarePage.close()

  const existingCoursewarePage = await newPage(browser, base, 'courseware-existing')
  await existingCoursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  assert.ok((await existingCoursewarePage.locator('.details-scroll').innerText()).includes('失败页面'), 'embedded courseware detail should be readable')
  const coursewareTaskActions = existingCoursewarePage.locator('.courseware-generation-page .details-panel > .panel-title .task-actions')
  assert.equal(await coursewareTaskActions.count(), 1, 'courseware task actions should occupy the details heading slot')
  assert.equal(await coursewareTaskActions.getAttribute('role'), 'group', 'courseware task actions should expose group semantics')
  assert.equal(await coursewareTaskActions.getAttribute('aria-label'), '课件任务操作', 'courseware task actions should be named')
  assert.ok(await coursewareTaskActions.getByRole('button', { name: '刷新状态', exact: true }).count(), 'courseware details heading should expose its refresh action')
  assert.ok(await coursewareTaskActions.getByRole('button', { name: '追加资源', exact: false }).count(), 'courseware details heading should retain append actions')
  const coursewareDetailPath = '/api/resources/courseware/jobs/cw-existing/detail'
  await existingCoursewarePage.waitForTimeout(120)
  let detailReadsBefore = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length
  await coursewareTaskActions.getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length > detailReadsBefore, 'courseware heading refresh read')
  const headingRefreshReads = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length - detailReadsBefore
  assert.ok(headingRefreshReads >= 1, 'courseware heading refresh should query the currently selected job')
  detailReadsBefore = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length
  await existingCoursewarePage.locator('.courseware-generation-page .process-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length > detailReadsBefore, 'courseware process refresh read')
  const processRefreshReads = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length - detailReadsBefore
  assert.ok(processRefreshReads >= 1, 'courseware process refresh should query the same currently selected job')
  evidence.interactionChecks.push({ scenario: 'courseware-refresh-entry-points', path: coursewareDetailPath, headingRefreshReads, processRefreshReads })
  await existingCoursewarePage.getByRole('button', { name: '重试任务' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/cw-existing/retry')), 'courseware task retry')
  assert.ok(state.writes.some((item) => item.path.endsWith('/cw-existing/retry')), 'courseware task retry should remain available')
  evidence.interactionChecks.push({ scenario: 'courseware-task-retry', writes: state.writes })
  await assertNoExternalOrUnexpected('courseware-task-retry')
  await existingCoursewarePage.close()

  const sceneRetryPage = await newPage(browser, base, 'courseware-existing')
  await sceneRetryPage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  await sceneRetryPage.getByRole('button', { name: '重试此页' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/scenes/scene-failed/retry')), 'courseware scene retry')
  assert.ok(state.writes.some((item) => item.path.endsWith('/scenes/scene-failed/retry')), 'courseware scene retry should remain available')
  evidence.interactionChecks.push({ scenario: 'courseware-scene-retry', writes: state.writes })
  await assertNoExternalOrUnexpected('courseware-scene-retry')
  await sceneRetryPage.close()
}

async function testReducedMotionAndMobile(browser, base) {
  const page = await newPage(browser, base, 'completed', { width: 390, height: 844 }, { reducedMotion: true })
  const metrics = await geometry(page, '390x844-reduced-motion', false)
  assert.ok(metrics.document.width <= 391, 'mobile reduced-motion page should not overflow horizontally')
  const activeAnimations = await page.evaluate(() => document.getAnimations({ subtree: true })
    .filter((animation) => ['running', 'pending'].includes(animation.playState)
      && Number.isFinite(animation.effect?.getComputedTiming().endTime)
      && animation.effect.getComputedTiming().endTime > 0)
    .map((animation) => ({ name: animation.animationName || '', state: animation.playState, target: animation.effect?.target?.className || '' })))
  assert.deepEqual(activeAnimations, [], 'reduced-motion should not leave non-essential UI animations running')
  await assertContrast(page, '390x844-reduced-motion')
  await capture(page, 'mobile-completed-reduced-motion')
  evidence.motionChecks.push({ viewport: page.viewportSize(), reducedMotion: true, activeAnimations })
  await assertNoExternalOrUnexpected('mobile-reduced-motion')
  await page.close()
}

async function run() {
  mkdirSync(reportDir, { recursive: true })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const base = 'http://127.0.0.1:' + server.address().port
  let browser
  let failure = null
  try {
    browser = await chromium.launch(browserOptions('GENERATION_BROWSER_CHANNEL'))
    await testStateMatrix(browser, base)
    await testPreparationResponsiveStates(browser, base)
    await testLearningPreparationStates(browser, base)
    await testDesktopFitMatrix(browser, base)
    await testNaturalFallback(browser, base)
    await testSwitchesRefreshAndErrors(browser, base)
    await testResourceSwitchAndLearningRoutes(browser, base)
    await testClaimAndAppend(browser, base)
    await testRetriesAndCourseware(browser, base)
    await testReducedMotionAndMobile(browser, base)
    console.log('generation browser tests passed')
  } catch (error) {
    failure = error
    console.error('generation browser tests failed:', error.stack || error)
  } finally {
    for (const response of state.sseClients) response.end()
    if (browser) await browser.close().catch(() => {})
    await new Promise((resolve) => server.close(resolve))
    const summary = {
      status: failure ? 'FAIL' : 'PASS',
      failure: failure ? String(failure.stack || failure) : null,
      screenshots: evidence.screenshots,
      counts: {
        scenarios: evidence.scenarios.length,
        layouts: evidence.layoutChecks.length,
        scroll: evidence.scrollChecks.length,
        interactions: evidence.interactionChecks.length,
        contrast: evidence.contrastChecks.length,
        motion: evidence.motionChecks.length,
        writes: fixtureAudit.writes.length,
        unexpectedApi: fixtureAudit.unexpectedApi.length,
        externalRequests: externalRequests.length,
        pageErrors: browserErrors.length,
      },
      evidence,
      requests: fixtureAudit.requests,
      writes: fixtureAudit.writes,
      unexpectedApi: fixtureAudit.unexpectedApi,
      externalRequests,
      browserErrors,
    }
    writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
    if (failure) process.exitCode = 1
  }
}

await run()
