import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = process.env.TEST_RUN_OUTPUT ? path.join(process.env.TEST_RUN_OUTPUT, 'e14-round') : path.join(frontend, 'tests/test-results/e14-round')
assert.ok(existsSync(path.join(dist, 'index.html')), 'Build frontend first')
mkdirSync(evidence, { recursive: true })
const audit = { requests: [], writes: [], unexpected: [], errors: [], external: [] }
const learnerId = 'e14-learner'
let legacy = false
let submitted = false
let corrected = false
let gradingReads = 0
let recoveryMode = false
let recoveryExpired = false
let recovered = false
const member = (index, extra = {}) => ({ member_id: `m${index}`, node_id: `n${index}`, role: legacy ? 'legacy' : index === 1 ? 'primary' : 'review', node_name: index === 1 ? '检索主节点' : '证据复习节点', state: 'awaiting_assessment', ...extra })
const mapping = (index, correction = false) => ({ ...member(index), stage_node_id: `sn${index}`, job_ids: [`run-${correction ? 'correction-' : ''}${index}`], resource_types: correction ? ['纠错包', '分阶测试题'] : index === 1 ? ['讲义', '分阶测试题'] : ['复习清单', '分阶测试题'], resource_ids: [], batch_id: `batch-${index}`, difficulty: index === 1 ? '中级' : '初级' })
const detail = () => ({ schema_version: '1.0', round_id: 'round-1', learner_id: learnerId, protocol_version: legacy ? 'legacy-correction/v1' : 'learning-round/v1', created_at: '2026-11-01T00:00:00Z', members: [member(1), member(2)], stages: [{ stage_id: 'stage-0', kind: 'initial', ordinal: 0, state: 'awaiting_assessment', members: [mapping(1), mapping(2)] }, ...(corrected ? [{ stage_id: 'stage-1', kind: 'correction', ordinal: 1, state: 'awaiting_assessment', members: [mapping(1, true), mapping(2, true)] }] : [])], available_actions: ['evaluate', 'correct', 'next', ...(legacy ? [] : ['append_primary'])] })
const question = index => ({ question_id: `q${index}`, question_type: 'short_answer', question: `描述节点 ${index} 的证据依据`, options: [], skill_node_id: `n${index}`, knowledge_point: `节点${index}`, difficulty: '中级', source: 'resource' })
const session = () => ({ schema_version: '1.0', round_id: 'round-1', stage_id: 'stage-0', session_id: 'session-1', manifest_hash: 'a'.repeat(64), groups: [1, 2].map(index => ({ ...member(index), questions: [question(index)] })) })
const feedback = () => ({ schema_version: '1.0', round_id: 'round-1', stage_id: 'stage-0', session_id: 'session-1', attempt_id: 'attempt-joint', profile_version: 2, primary_path_action: 'remediate', nodes: [1, 2].map(index => ({ ...member(index), score: index === 1 ? 0.4 : 0.2, action: 'remediate', reason: `节点 ${index} 仍需补救`, correction_eligible: true, remediation_status: 'remediate', source_attempt_id: `attempt-node-${index}` })) })
const jobs = () => detail().stages.flatMap(stage => stage.members.map(scope => ({ run_id: scope.job_ids[0], learner_id: learnerId, batch_id: scope.batch_id, status: 'completed', job_status: 'completed', created_at: '2026-11-01T00:00:00Z', finished_at: '2026-11-01T00:01:00Z', round_binding: { round_id: 'round-1', stage_id: stage.stage_id, member_id: scope.member_id, stage_node_id: scope.stage_node_id, node_id: scope.node_id, role: scope.role, protocol_version: detail().protocol_version }, request_payload: { resource_types: scope.resource_types, include_review: false, learner_id: learnerId } })))
const resource = job => ({ resource_id: `resource-${job.run_id}`, learner_id: learnerId, run_id: job.run_id, batch_id: job.batch_id, title: `${job.run_id} 独立材料`, topic: '轮次专项', resource_type: job.request_payload.resource_types[0], resource_kind: 'learning_document', content_text: `# ${job.run_id} 正文标题\n\n节点正文标记：${job.run_id}-body。`, difficulty: '中级', knowledge_points: [], source_refs: [], version: 1, publication_status: 'published', created_at: '2026-11-01T00:00:00Z' })
function json(res, value, status = 200) { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(value)) }
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    let raw = ''; for await (const chunk of req) raw += chunk
    const body = raw ? JSON.parse(raw) : null
    const entry = { method: req.method, path: url.pathname, query: url.search, body }
    audit.requests.push(entry); if (req.method !== 'GET') audit.writes.push(entry)
    const p = url.pathname
    if (p === '/api/auth/me') return json(res, { user: { user_id: 'e14-user', username: 'e14', display_name: '轮次验收' } })
    if (p === '/api/profiles/') return json(res, { items: [{ learner_id: learnerId, learner_type: '个人学习者', knowledge_base_id: 'track-1', skill_level: '中级', profile_version: 1, learning_goal: '检索与证据' }], total: 1 })
    if (p === '/api/knowledge/domains') return json(res, { domains: [{ domain_id: 'd1', tracks: [{ track_id: 'track-1', name: '证据学习' }] }] })
    if (p === '/api/skills/nodes' || p.startsWith('/api/knowledge/')) return json(res, { nodes: [] })
    if (p === '/api/generate/capabilities') return json(res, { round_creation_enabled: true })
    if (p === '/api/generate/jobs') return json(res, { items: jobs(), total: jobs().length })
    if (p.startsWith('/api/generate/jobs/')) return json(res, jobs().find(job => p.endsWith(job.run_id)))
    if (p === '/api/resources/courseware/jobs') return json(res, { items: [] })
    if (p === `/api/resources/${learnerId}`) return json(res, { resources: jobs().filter(job => !url.searchParams.get('run_id') || job.run_id === url.searchParams.get('run_id')).map(resource) })
    if (p.startsWith('/api/resources/items/')) { const item = jobs().map(resource).find(item => p.includes(item.resource_id)); return json(res, { resource: item, content_text: item?.content_text }) }
    if (p === `/api/feedback/results/${learnerId}`) return json(res, [])
    if (p === '/api/feedback/rounds/round-1') return json(res, detail())
    if (p.endsWith('/candidates')) return json(res, { profile_version: 2, generation_options: {}, eligible_review_nodes: [], correction_targets: [1, 2].map(index => ({ node_id: `n${index}`, source_attempt_id: `attempt-node-${index}` })) })
    if (p.endsWith('/evaluation-session')) return json(res, session())
    if (p.endsWith('/result')) {
      if (!submitted) return json(res, { state: 'not_submitted', round_id: 'round-1', stage_id: 'stage-0' })
      if (recoveryMode && !recovered) return recoveryExpired
        ? json(res, { state: 'not_submitted', round_id: 'round-1', stage_id: 'stage-0' })
        : json(res, { state: 'grading', session_id: 'session-1', retry_after_seconds: 2 }, 202)
      if (++gradingReads === 1) return json(res, { state: 'grading', attempt_id: 'attempt-joint' }, 202)
      return json(res, feedback())
    }
    if (p.endsWith('/attempts')) {
      if (recoveryMode && submitted) { recovered = true; return json(res, feedback()) }
      submitted = true
      return json(res, { state: 'grading', session_id: 'session-1', retry_after_seconds: 2 }, 202)
    }
    if (p.endsWith('/corrections')) {
      corrected = true
      return json(res, { schema_version: '1.0', round_id: 'round-1', stage_id: 'stage-1', primary_node_id: legacy ? null : 'n1', state: 'producing', primary_default_run_id: legacy ? null : 'run-correction-1', members: [mapping(1, true), mapping(2, true)] })
    }
    const run = p.match(/^\/api\/runs\/([^/]+)\/(.+)$/)
    if (run) {
      if (run[2] === 'timeline') return json(res, { run: { run_id: run[1], status: 'completed' }, events: [{ run_id: run[1], event_id: `evt-${run[1]}`, sequence: 1, event_sequence: 1, event_type: 'step_succeeded', step_id: `step-${run[1]}`, node_name: 'generate', agent_name: `${run[1]} 专属轨迹`, action: '生成', status: 'success', payload: {}, occurred_at: '2026-11-01T00:00:00Z' }], resource_executions: [], next_event_sequence: null, replay_completeness: 'complete' })
      if (run[2] === 'resource-quality') return json(res, { run_id: run[1], items: [] })
      if (run[2] === 'claims') return json(res, { items: [] })
      if (run[2] === 'events') { res.writeHead(200, { 'content-type': 'text/event-stream' }); return res.end(`event: run_snapshot\ndata: ${JSON.stringify({ run_id: run[1], status: 'completed', is_terminal: true })}\n\n`) }
    }
    audit.unexpected.push(entry); return json(res, { message: 'Unexpected E14 fixture request' }, 404)
  }
  const candidate = path.resolve(dist, `.${decodeURIComponent(url.pathname)}`)
  const file = candidate.startsWith(dist + path.sep) && existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, 'index.html')
  const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }
  res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream' }); res.end(readFileSync(file))
})
let browser
let activePage
const result = { status: 'RUNNING', evidence_type: 'built_app_browser_fixture', checks: [], audit }
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${server.address().port}`
  browser = await chromium.launch(browserOptions('E14_BROWSER_CHANNEL'))
  const page = await browser.newPage({ viewport: { width: 1393, height: 1000 } })
  activePage = page
  page.setDefaultTimeout(10000)
  page.on('pageerror', error => audit.errors.push(error.message))
  page.on('request', request => { if (/^https?:/.test(request.url()) && !request.url().startsWith(base)) audit.external.push(request.url()) })
  await page.addInitScript(() => { localStorage.clear(); localStorage.setItem('app_sidebar_collapsed', 'true') })
  await page.goto(`${base}/generate?learnerId=${learnerId}&roundId=round-1&stageId=stage-0&runId=run-1`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /主学习.*检索主节点/ }).waitFor()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-1-body').waitFor()
  const review = page.getByRole('button', { name: /附带复习.*证据复习节点/ })
  await review.focus(); await page.keyboard.press('Enter')
  await page.waitForURL(/runId=run-2/)
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-2-body').waitFor()
  assert.equal(await review.getAttribute('aria-pressed'), 'true')
  assert.ok(audit.requests.some(entry => entry.path === '/api/runs/run-2/timeline'))
  assert.equal(await page.getByRole('region', { name: '学习资源预览' }).getByText('run-1-body').count(), 0)
  assert.match(await page.locator('.status-action-append').innerText(), /主节点/)
  await page.screenshot({ path: path.join(evidence, 'desktop-two-members.png'), fullPage: true })
  result.checks.push('Real generation page switches Run, trace and resource scope by unique memberId; keyboard and primary append label')
  await page.goto(`${base}/feedback?learnerId=${learnerId}&roundId=round-1&stageId=stage-0`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: '检索主节点 第 1 题答案' }).fill('检索依据')
  assert.equal(await page.getByRole('button', { name: '统一提交本次测评' }).isDisabled(), true)
  await page.getByRole('textbox', { name: '证据复习节点 第 1 题答案' }).fill('来源核验')
  await page.getByRole('button', { name: '统一提交本次测评' }).click()
  await page.getByRole('region', { name: '各节点独立测评结果' }).getByText('40 分').waitFor()
  await page.getByText('20 分', { exact: true }).waitFor()
  const submissions = audit.writes.filter(entry => entry.path.endsWith('/attempts'))
  assert.equal(submissions.length, 1); assert.equal(submissions[0].body.answers.length, 2)
  assert.ok(audit.requests.filter(entry => entry.path.endsWith('/result')).length >= 3)
  await page.getByRole('button', { name: '生成选中节点的纠错包与新测试题' }).click()
  await page.waitForURL(/stageId=stage-1/)
  const correction = audit.writes.find(entry => entry.path.endsWith('/corrections'))
  assert.deepEqual(correction.body.targets, [{ node_id: 'n1', source_attempt_id: 'attempt-node-1' }, { node_id: 'n2', source_attempt_id: 'attempt-node-2' }])
  assert.equal(detail().stages[1].members.reduce((n, member) => n + member.resource_types.length, 0), 4)
  await page.getByRole('button', { name: /附带复习.*证据复习节点/ }).click()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-correction-2-body').waitFor()
  result.checks.push('Joint groups require all answers, one POST, independent scores, 202 result polling, two correction targets retain own source attempt and same round')
  legacy = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /历史节点.*检索主节点/ }).waitFor()
  assert.equal(await page.getByRole('button', { name: /历史节点/ }).count(), 2)
  await page.getByRole('button', { name: /历史节点.*检索主节点/ }).click()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-correction-1-body').waitFor()
  assert.equal(await page.locator('.status-action-append').isDisabled(), true)
  await page.setViewportSize({ width: 375, height: 812 })
  const legacyReview = page.getByRole('button', { name: /历史节点.*证据复习节点/ })
  await legacyReview.waitFor()
  await legacyReview.focus(); await page.keyboard.press('Enter')
  await page.waitForURL(/runId=run-correction-2/)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
  assert.equal(overflow, false)
  await page.screenshot({ path: path.join(evidence, 'mobile-legacy-members.png'), fullPage: true })
  result.checks.push('Legacy two members remain distinct across refresh, no invented primary/append, mobile keyboard selection without horizontal page overflow')
  legacy = false; corrected = false; submitted = false; gradingReads = 0; recoveryMode = true
  const recoveryStart = audit.writes.length
  await page.setViewportSize({ width: 1393, height: 1000 })
  await page.goto(`${base}/feedback?learnerId=${learnerId}&roundId=round-1&stageId=stage-0`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: '检索主节点 第 1 题答案' }).fill('恢复前的主节点答案')
  await page.getByRole('textbox', { name: '证据复习节点 第 1 题答案' }).fill('恢复前的复习答案')
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/attempts') && response.status() === 202),
    page.getByRole('button', { name: '统一提交本次测评' }).click(),
  ])
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByText('正在恢复本轮测评状态。', { exact: true }).waitFor()
  recoveryExpired = true
  await page.getByText('评分已中断，可使用相同提交内容重试。', { exact: true }).waitFor()
  assert.equal(await page.getByRole('textbox', { name: '检索主节点 第 1 题答案' }).inputValue(), '恢复前的主节点答案')
  assert.equal(await page.getByRole('textbox', { name: '证据复习节点 第 1 题答案' }).inputValue(), '恢复前的复习答案')
  assert.equal(await page.getByRole('button', { name: '统一提交本次测评' }).isEnabled(), true)
  await page.screenshot({ path: path.join(evidence, 'expired-scoring-recovery.png'), fullPage: true })
  await page.getByRole('button', { name: '统一提交本次测评' }).click()
  await page.getByRole('region', { name: '各节点独立测评结果' }).getByText('40 分').waitFor()
  const recoverySubmissions = audit.writes.slice(recoveryStart).filter(entry => entry.path.endsWith('/attempts'))
  assert.equal(recoverySubmissions.length, 2)
  assert.deepEqual(recoverySubmissions[0].body, recoverySubmissions[1].body)
  result.checks.push('A crashed scoring owner becomes resumable after refresh; frozen answers, original key and full payload survive, then one explicit recovery POST completes')
  assert.deepEqual(audit.errors, []); assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, [])
  result.status = 'PASS'
} catch (error) { result.status = 'FAIL'; result.error = error.stack; process.exitCode = 1; if (activePage) { await activePage.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }); writeFileSync(path.join(evidence, 'failure-body.txt'), await activePage.locator('body').innerText()) } }
finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify(result, null, 2)); console.log(`${result.status}: E14 built-app browser (${result.checks.length} scenarios)`); if (result.error) console.error(result.error) }
