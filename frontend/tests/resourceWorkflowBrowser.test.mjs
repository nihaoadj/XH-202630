// T51: the built GenerateView, isolated HTTP/SSE fixtures, no user backend/model.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = path.resolve(process.env.TEST_RUN_OUTPUT || path.join(frontend, 'tests/test-results/resource-workflow'))
assert.ok(existsSync(path.join(dist, 'index.html')), 'Build frontend first')
mkdirSync(evidence, { recursive: true })
const learnerId = 't51-learner'
const audit = { requests: [], writes: [], errors: [], external: [], unexpected: [] }
const checks = []
const datasets = new Map()
let heldTimeline = null
let delayNextMainTimeline = false
const streams = new Map()

function fixture(runId, types, { mixed = false, round = false, member = 'a', stage = 'initial', legacy = false, empty = false, noArtifact = false } = {}) {
  const artifact = (index, version = 1) => ({
    run_id: runId, learner_id: learnerId, resource_id: `${runId}-${index}-v${version}`, resource_spec_id: `${runId}-spec-${index}`,
    resource_type: types[index], representation: 'text', resource_kind: 'learning_document', version,
    parent_resource_id: version > 1 ? `${runId}-${index}-v${version - 1}` : null,
    difficulty: '中级', topic: '列表与循环', knowledge_points: [member === 'a' ? 'node-a' : 'node-b'], source_refs: [],
    content_text: `# ${types[index]} v${version}\n\n${runId} / ${types[index]} / v${version} 专属正文。`,
    file_path: `${runId}-${index}-v${version}.md`,
    review_status: mixed && index > 0 ? 'human_review' : 'approved', publication_status: mixed && index > 0 ? 'unpublished' : 'published',
    claim_publish_decision_pending: mixed && index === 2,
    created_at: '2026-11-08T00:00:00Z',
  })
  const resources = empty || noArtifact ? [] : types.map((_, index) => artifact(index))
  if (mixed) resources.push(artifact(1, 2))
  const current = empty ? [] : types.map((type, index) => ({ ...(noArtifact ? {} : artifact(index, mixed && index === 1 ? 2 : 1)),
    key: `${runId}-spec-${index}:text`, resource_spec_id: `${runId}-spec-${index}`, resource_type: type, representation: 'text',
    resource_execution_state: noArtifact ? 'failed' : mixed && index > 0 ? 'human_review' : 'approved',
    attempt: mixed && index === 1 ? 2 : 1, display_order: index + 1,
    ...(noArtifact ? { error_code: 'GENERATION_FAILED', publication_status: 'unpublished' } : {}),
  }))
  const steps = [], events = []
  const addStep = (node, ids = []) => {
    const item = { run_id: runId, step_id: `${runId}-step-${steps.length + 1}`, step_sequence: steps.length + 1,
      node_name: node, agent_name: node, action: `${runId} ${node}`, status: 'success', resource_ids: ids,
      review_ids: [], duration_ms: 1200, started_at: '2026-11-08T00:00:00Z' }
    steps.push(item); return item
  }
  const addEvent = (type, step, resource, payload = {}) => {
    events.push({ event_id: `${runId}-event-${events.length + 1}`, event_sequence: events.length + 1,
      run_id: runId, step_id: step.step_id, step_sequence: step.step_sequence, node_name: step.node_name,
      event_type: type, status: 'completed', occurred_at: '2026-11-08T00:00:01Z',
      payload: { resource_id: resource?.resource_id, resource_spec_id: resource?.resource_spec_id,
        resource_type: resource?.resource_type, representation: 'text', version: resource?.version,
        parent_resource_id: resource?.parent_resource_id, ...payload } })
  }
  if (!empty) {
    for (const node of ['diagnose', 'retrieve', 'evidence_gate', 'plan']) addStep(node)
    const gen = addStep('generate', legacy || noArtifact ? [] : resources.filter(r => r.version === 1).map(r => r.resource_id))
    if (noArtifact) addEvent('resource_execution_failed', gen, current[0], { resource_execution_state: 'failed' })
    else if (!legacy) {
      for (const resource of resources.filter(r => r.version === 1)) addEvent('resource_generated', gen, resource, { resource_execution_state: 'generated', attempt: 1 })
      const review = addStep('review', [...gen.resource_ids])
      for (const resource of resources.filter(r => r.version === 1)) addEvent('review_persisted', review, resource, {
        resource_execution_state: mixed && resource.resource_type === types[1] ? 'revision_requested' : 'approved',
      })
      if (mixed) {
        addStep('prepare_revision', [...gen.resource_ids])
        const revised = resources.find(r => r.version === 2)
        const gen2 = addStep('generate', [revised.resource_id])
        addEvent('resource_generated', gen2, revised, { resource_execution_state: 'generated', attempt: 2 })
        const review2 = addStep('review', [revised.resource_id])
        addEvent('review_persisted', review2, revised, { resource_execution_state: 'human_review', attempt: 2 })
      }
      const claimResources = current.filter((_, index) => !mixed || index !== 1)
      const claim = addStep('claim_judge', claimResources.map(item => item.resource_id))
      for (const resource of claimResources) addEvent('claim_metric_computed', claim, resource, {
        claim_metric_status: 'complete', factual_claim_total: 3, supported_claim_total: mixed && resource.resource_type === types[2] ? 2 : 3,
      })
      const finish = addStep('finalize', current.map(item => item.resource_id))
      for (const resource of current.filter(item => item.publication_status === 'published')) addEvent('resource_published', finish, resource, { publication_status: 'published', resource_execution_state: 'approved' })
    }
  }
  const binding = round ? { round_id: 'round-t51', member_id: member, node_id: `node-${member}`, stage_id: stage, stage_node_id: `${stage}-${member}`, role: member === 'a' ? 'primary' : 'review', protocol_version: 'learning-round/v1' } : null
  const published = current.filter(item => item.publication_status === 'published').length
  const job = { run_id: runId, learner_id: learnerId, batch_id: `batch-${runId}`, job_status: empty ? 'queued' : 'completed',
    created_at: '2026-11-08T00:00:00Z', round_binding: binding,
    request_payload: { learner_id: learnerId, topic: '列表与循环', target_skill_nodes: [`node-${member}`], resource_types: types, include_review: true, include_claim_check: true },
    publish_summary: { completeness: 'complete', total: types.length, published, unpublished: types.length - published, pending_review: mixed ? 2 : 0 },
    resource_progress_summary: { total: types.length, published, items: current },
  }
  const timeline = { run: { run_id: runId, status: empty ? 'running' : 'completed', last_event_sequence: events.length },
    steps, events, resource_versions: resources, resource_executions: current, reviews: [], evidence: [], replay_completeness: legacy ? 'legacy_partial' : 'complete', next_event_sequence: null }
  const result = { job, timeline, resources }; datasets.set(runId, result); return result
}
fixture('run-main', ['讲义', '实操指南', '案例分析'], { mixed: true, round: true })
const older = fixture('run-older', ['讲义', '实操指南', '案例分析'], { mixed: true })
older.resources.find(item => item.resource_id === 'run-older-1-v1').publication_status = 'published'
fixture('run-extra', ['分阶测试题'], { round: true })
fixture('run-review', ['复习清单', '分阶测试题'], { round: true, member: 'b' })
fixture('run-correction-a', ['纠错包', '分阶测试题'], { round: true, stage: 'correction' })
fixture('run-correction-b', ['纠错包', '分阶测试题'], { round: true, member: 'b', stage: 'correction' })
fixture('run-legacy', ['讲义'], { legacy: true })
fixture('run-empty', ['讲义', '实操指南'], { empty: true })
fixture('run-no-artifact', ['讲义'], { noArtifact: true })
const member = id => ({ member_id: id, node_id: `node-${id}`, node_name: id === 'a' ? '列表与循环' : '条件判断', role: id === 'a' ? 'primary' : 'review', state: 'awaiting_assessment' })
const scope = (id, jobIds) => ({ ...member(id), stage_node_id: `scope-${id}`, job_ids: jobIds, resource_types: id === 'a' ? ['讲义', '实操指南', '案例分析'] : ['复习清单', '分阶测试题'], resource_ids: [] })
const roundDetail = { round_id: 'round-t51', learner_id: learnerId, protocol_version: 'learning-round/v1', members: [member('a'), member('b')],
  stages: [{ stage_id: 'initial', kind: 'initial', ordinal: 0, members: [scope('a', ['run-main', 'run-extra']), scope('b', ['run-review'])] },
    { stage_id: 'correction', kind: 'correction', ordinal: 1, members: [scope('a', ['run-correction-a']), scope('b', ['run-correction-b'])] }], available_actions: ['evaluate', 'correct', 'append_primary'] }
const json = (res, value, code = 200) => { res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(value)) }
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://fixture')
  const p = url.pathname
  if (p.startsWith('/api/')) {
    audit.requests.push(p + url.search)
    if (req.method !== 'GET') { audit.writes.push(p); return json(res, { message: 'writes forbidden in T51 fixture' }, 405) }
    if (p === '/api/auth/me') return json(res, { user: { user_id: 't51-user', username: 't51', display_name: '展示专项' } })
    if (p === '/api/profiles/') return json(res, { items: [{ learner_id: learnerId, learner_type: '个人学习者', knowledge_base_id: 'track', skill_level: '中级', profile_version: 1 }], total: 1 })
    if (p === '/api/knowledge/domains') return json(res, { domains: [{ domain_id: 'domain', tracks: [{ track_id: 'track', name: 'Python 基础' }] }] })
    if (p === '/api/skills/nodes') return json(res, { nodes: [{ node_id: 'node-a', name: '列表与循环', tier: 1 }, { node_id: 'node-b', name: '函数基础', tier: 1 }] })
    if (p === '/api/generate/capabilities') return json(res, { round_creation_enabled: true })
    if (p === '/api/generate/jobs') return json(res, { items: [...datasets.values()].map(item => item.job) })
    if (p.startsWith('/api/generate/jobs/')) return json(res, datasets.get(p.split('/').at(-1))?.job)
    if (p === '/api/resources/courseware/jobs') return json(res, { items: [] })
    if (p === `/api/resources/${learnerId}`) {
      const resources = (datasets.get(url.searchParams.get('run_id'))?.resources || []).filter(item => item.publication_status === 'published')
      return json(res, { resources, total: resources.length })
    }
    if (p.startsWith('/api/resources/items/')) {
      const resource = [...datasets.values()].flatMap(item => item.resources).find(item => item.resource_id === decodeURIComponent(p.split('/')[4]))
      return json(res, { resource, content_text: resource?.content_text })
    }
    if (p === '/api/feedback/rounds/round-t51') return json(res, roundDetail)
    if (p === `/api/feedback/results/${learnerId}`) return json(res, [])
    const match = p.match(/^\/api\/runs\/([^/]+)\/(.+)$/)
    if (match) {
      const data = datasets.get(match[1]); const kind = match[2]
      if (kind === 'timeline') {
        if (delayNextMainTimeline && match[1] === 'run-main') { delayNextMainTimeline = false; heldTimeline = () => json(res, data.timeline); return }
        return json(res, data.timeline)
      }
      if (kind === 'resource-quality') return json(res, { run_id: match[1], items: [] })
      if (kind === 'claims') return json(res, { run_id: match[1], claims: [], judgements: [], resource_metrics: Object.fromEntries(data.resources.map(item => [item.resource_id, { metric_status: 'complete', factual_claim_total: 3, supported_claim_total: item.claim_publish_decision_pending ? 2 : 3 }])) })
      if (kind === 'claim-evidence-retrieval') return json(res, { run_id: match[1], requested: false, sessions: [] })
      if (kind === 'events') {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' })
        res.write(`event: snapshot\ndata: ${JSON.stringify({ run_id: match[1], run_status: data.timeline.run.status, is_terminal: data.timeline.run.status === 'completed', last_event_sequence: data.timeline.events.length })}\n\n`)
        const list = streams.get(match[1]) || []; list.push(res); streams.set(match[1], list)
        return
      }
    }
    audit.unexpected.push(p); return json(res, { message: 'unexpected T51 fixture request' }, 404)
  }
  const candidate = path.resolve(dist, `.${decodeURIComponent(p)}`)
  const file = candidate.startsWith(dist + path.sep) && existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, 'index.html')
  const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }
  res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream' }); res.end(readFileSync(file))
})

let browser, page
const summary = { status: 'RUNNING', evidence_type: 'built_frontend_http_sse_fixture', checks, audit }
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${server.address().port}`
  browser = await chromium.launch(browserOptions('RESOURCE_WORKFLOW_BROWSER_CHANNEL'))
  page = await browser.newPage({ viewport: { width: 1393, height: 1000 } })
  page.setDefaultTimeout(10000)
  page.on('pageerror', error => audit.errors.push(error.message))
  page.on('request', req => { if (/^https?:/.test(req.url()) && !req.url().startsWith(base)) audit.external.push(req.url()) })
  await page.addInitScript(() => {
    localStorage.clear(); localStorage.setItem('app_sidebar_collapsed', 'true')
    // Preserve the real EventSource transport while retaining a queued callback
    // so a late event is actually delivered even after the old socket closes.
    window.__t51StreamCallbacks = []
    const add = EventSource.prototype.addEventListener
    EventSource.prototype.addEventListener = function (type, listener, options) {
      if (type === 'step_succeeded') window.__t51StreamCallbacks.push({ url: this.url, listener })
      return add.call(this, type, listener, options)
    }
  })
  const open = run => page.goto(`${base}/generate?learnerId=${learnerId}&runId=${run}`, { waitUntil: 'domcontentloaded' })
  const graph = page.locator('.execution-graph')
  const pick = type => page.getByRole('navigation', { name: '选择资源执行链路' }).getByRole('button', { name: new RegExp(`^${type}，`) })
  const node = (run, ordinal) => graph.locator(`[data-step-id="${run}-step-${ordinal}"]`)
  const waitSteps = async count => { await graph.locator('.execution-graph-node').first().waitFor(); await page.waitForFunction(expected => document.querySelectorAll('.execution-graph-node').length === expected, count) }
  const assertContinuous = async count => {
    const labels = await graph.locator('.execution-graph-sequence').allTextContents()
    assert.deepEqual(labels, Array.from({ length: count }, (_, i) => `STEP ${String(count - i).padStart(2, '0')}`))
  }
  const showGraph = async () => { await graph.locator('.execution-graph-node').first().evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' })); await page.waitForTimeout(80) }
  const chooseRun = async run => {
    await page.locator('.task-selector .selector-field').nth(1).locator('.el-select').click()
    await page.locator(`.el-select-dropdown:visible [data-run-id="${run}"]`).click()
    await page.waitForURL(new RegExp(`runId=${run}(?:&|$)`))
  }
  const resourceAction = async label => {
    await page.getByRole('button', { name: '所选资源操作', exact: true }).click()
    await page.getByRole('menuitem', { name: label, exact: true }).click()
  }
  await open('run-main'); await pick('讲义').waitFor(); await waitSteps(8)
  const batchSelect = page.getByRole('combobox', { name: '资源批次' })
  await batchSelect.click()
  const batchMenu = page.locator('.generation-batch-dropdown:visible')
  const mainBatch = batchMenu.locator('[data-run-id="run-main"]')
  await mainBatch.waitFor()
  assert.match(await mainBatch.innerText(), /列表与循环[\s\S]*第 1 阶[\s\S]*部分发布[\s\S]*讲义/)
  await page.screenshot({ path: path.join(evidence, 'batch-picker.png') })
  await batchSelect.fill('RUN-MAIN')
  await batchMenu.locator('[data-run-id="run-extra"]').waitFor({ state: 'hidden' })
  await mainBatch.click()
  assert.equal(await node('run-main', 7).count(), 0, 'published lecture must not inherit sibling revision')
  for (let i = 1; i <= 4; i++) assert.equal(await node('run-main', i).count(), 1)
  assert.equal(await page.getByRole('button', { name: /重新生成失败资源/ }).count(), 0)
  await assertContinuous(8)
  assert.equal(await node('run-main', 10).locator('.execution-graph-sequence').getAttribute('title'), '原始 Run 步骤 #10')
  assert.match(await node('run-main', 11).innerText(), /已发布/)
  assert.equal(await page.locator('.execution-card,.resource-progress-tree,.round-stage-controls,.round-node-cards').count(), 0)
  assert.equal(await page.locator('.round-node-switch').count(), 1)
  assert.equal(await page.locator('.process-panel-heading .round-node-switch').count(), 1)
  const titleOrder = await page.locator('.process-panel-heading').evaluate(el => {
    const title=el.querySelector('h3').getBoundingClientRect(), toggle=el.querySelector('.round-node-switch').getBoundingClientRect()
    return toggle.left >= title.right || toggle.top >= title.bottom
  })
  assert.equal(titleOrder, true, 'the single node button follows the workflow title')
  assert.equal(await page.getByRole('button', { name: '本轮测评', exact: true }).count(), 0)
  assert.equal(await page.locator('.chain-heading,.chain-context').count(), 0)
  assert.equal(await page.locator('.round-node-switch').innerText(), '主学习')
  assert.match(await page.locator('.process-panel-heading .eyebrow').innerText(), /WORKFLOW/)
  assert.equal((await page.locator('.status-action-append').innerText()).replace(/\s/g,''), '追加资源')
  assert.equal(await pick('讲义').innerText(), '讲义')
  assert.equal(await page.locator('.summary-direction,.summary-count').count(), 0)
  assert.equal(await page.locator('.job-summary .summary-item').count(), 4)
  assert.equal(await page.locator('.production-status').innerText(), '部分发布')
  assert.doesNotMatch(await page.locator('.production-status').innerText(), /[0-9/]/)
  await showGraph(); await page.screenshot({ path: path.join(evidence, 'desktop-lecture.png'), fullPage: true })
  assert.equal(await page.locator('.resource-toolbar,.resource-select').count(), 0)
  await page.locator('.resource-panel-heading .learning-mode-action').waitFor()
  assert.equal(await page.getByRole('group', { name: '当前资源操作', exact: true }).count(), 0)
  await pick('实操指南').focus(); await page.keyboard.press('Enter'); await waitSteps(10)
  await assertContinuous(10)
  const resourceActions = page.getByRole('group', { name: '当前资源操作', exact: true })
  assert.equal(await resourceActions.getByRole('button', { name: '重试', exact: true }).count(), 1)
  assert.equal(await resourceActions.getByRole('button', { name: '发布', exact: true }).count(), 0)
  assert.equal(await pick('实操指南').getAttribute('aria-pressed'), 'true')
  assert.equal(await pick('实操指南').evaluate(el => document.activeElement === el), true)
  assert.match(await node('run-main', 6).innerText(), /需修订/)
  assert.match(await node('run-main', 9).innerText(), /待复核/)
  assert.match(await node('run-main', 8).innerText(), /v2/)
  assert.equal(await node('run-main', 11).evaluate(el => el.classList.contains('is-terminal')), false, 'unpublished batch finalization must not use success-green terminal styling')
  await page.getByRole('heading', { name: '实操指南尚未发布' }).waitFor()
  assert.doesNotMatch(await page.getByRole('region', { name: '学习资源预览' }).innerText(), /讲义.*第 1 阶/)
  assert.equal(await page.locator('.learning-mode-action').count(), 0)
  await showGraph(); await page.screenshot({ path: path.join(evidence, 'desktop-practice-revision.png'), fullPage: true })
  checks.push('shared stages and resource-only revisions preserved; no stage/job selectors or status cards; one node button follows the title; keyboard and reader preserved')

  await node('run-main', 5).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByText('run-main / 实操指南 / v1 专属正文。', { exact: true }).waitFor()
  assert.equal(await dialog.getByText('run-main / 讲义 / v1 专属正文。', { exact: true }).count(), 0)
  await dialog.getByRole('button', { name: '刷新数据' }).click()
  await dialog.getByText('run-main / 实操指南 / v1 专属正文。', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(evidence, 'exact-old-version-detail.png'), fullPage: true })
  await page.keyboard.press('Escape'); await pick('案例分析').click(); await waitSteps(8); await assertContinuous(8)
  assert.match(await node('run-main', 10).innerText(), /发现事实风险/)
  assert.doesNotMatch(await node('run-main', 11).innerText(), /已发布/)
  assert.equal(await pick('案例分析').innerText(), '案例分析')
  assert.match(await pick('案例分析').getAttribute('title'), /待你决定发布/)
  await page.getByRole('group', { name: '当前资源操作', exact: true }).getByRole('button', { name: '发布', exact: true }).click()
  await page.locator('.claim-report-dialog').waitFor({ state: 'visible' })
  assert.match(await page.locator('.claim-report-dialog').innerText(), /66\.7%/)
  let decisionUrl = ''
  await page.route('**/api/resources/items/**/claim-publication-decision', route => {
    decisionUrl = route.request().url()
    return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'T51 fixture: no state mutation' }) })
  })
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/claim-publication-decision')),
    page.locator('.claim-report-dialog').getByRole('button', { name: '发布', exact: true }).click(),
  ])
  assert.ok(decisionUrl.endsWith('/run-main-2-v1/claim-publication-decision'), 'report action stays on the selected case artifact; HTTP intercepted before fixture/backend')
  await page.keyboard.press('Escape')
  await resourceAction('查看过程详情')
  await page.getByRole('dialog', { name: '资源审核详情' }).waitFor()
  await page.keyboard.press('Escape')
  checks.push('clicked generation opens exact old version across detail refresh; Claim risk and publication stay separate')

  await resourceAction('查看批次记录'); await waitSteps(11); await assertContinuous(11)
  assert.equal(await page.locator('.execution-card,.resource-progress-tree').count(), 0)
  await resourceAction('返回资源链路'); await waitSteps(8)
  await pick('讲义').click(); await resourceAction('查看已发布资源')
  assert.match(await page.getByRole('region', { name: '学习资源预览' }).innerText(), /run-main \/ 讲义 \/ v1/)
  await pick('实操指南').click()
  const retryButton = page.getByRole('group', { name: '当前资源操作', exact: true }).getByRole('button', { name: '重试', exact: true })
  await retryButton.waitFor()
  let retryUrl = ''
  await page.route('**/api/generate/jobs/**/resource-specs/**/representations/**/retry', route => {
    retryUrl = route.request().url()
    return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'T51 fixture: no state mutation' }) })
  })
  await Promise.all([
    page.waitForResponse(response => response.url().includes('/representations/text/retry')),
    retryButton.click(),
  ])
  assert.ok(retryUrl.endsWith('/run-main/resource-specs/run-main-spec-1/representations/text/retry'), 'retry targets current attempt spec, not the reader or a sibling')
  await pick('案例分析').click(); await waitSteps(8)
  checks.push('full batch records remain reachable; read, audit report, retry and process detail are available in the exact-resource menu')

  // A delayed detail response and old stream may complete after a node switch.
  delayNextMainTimeline = true
  await node('run-main', 5).click()
  await page.waitForFunction(() => Boolean(document.querySelector('.audit-loading')))
  assert.ok(heldTimeline, 'the old detail response must actually be held')
  // Modal blocks background interaction; close it exactly as a user would.
  await page.keyboard.press('Escape')
  await page.locator('.round-node-switch').focus(); await page.keyboard.press('Enter')
  await page.waitForURL(/runId=run-review/); await pick('复习清单').waitFor(); await waitSteps(8)
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  await pick('分阶测试题').click()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-review / 分阶测试题 / v1 专属正文。', { exact: true }).waitFor()
  await pick('复习清单').click()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-review / 复习清单 / v1 专属正文。', { exact: true }).waitFor()
  heldTimeline?.(); heldTimeline = null
  const stale = { event_id: 'late-old', run_id: 'run-main', sequence: 900, event_type: 'step_succeeded', node_name: 'generate', step_id: 'late-old-step', payload: { resource_ids: ['run-main-0-v1'] } }
  for (const res of streams.get('run-main') || []) if (!res.destroyed) res.write(`event: step_succeeded\ndata: ${JSON.stringify(stale)}\n\n`)
  const delivered = await page.evaluate(payload => {
    const callbacks = window.__t51StreamCallbacks.filter(item => item.url.includes('/runs/run-main/'))
    for (const item of callbacks) item.listener(new MessageEvent('step_succeeded', { data: JSON.stringify(payload) }))
    return callbacks.length
  }, stale)
  assert.ok(delivered > 0, 'must invoke a queued old-Run callback, not merely write to an already closed socket')
  await page.waitForTimeout(100)
  assert.equal(await graph.locator('[data-step-id^="run-main"]').count(), 0)
  assert.equal(await page.getByRole('dialog').count(), 0)
  assert.doesNotMatch(await page.getByRole('region', { name: '学习资源预览' }).innerText(), /run-main/)
  await showGraph(); await page.screenshot({ path: path.join(evidence, 'review-node-isolation.png'), fullPage: true })
  await chooseRun('run-correction-b')
  await page.waitForURL(/runId=run-correction-b/); await pick('纠错包').waitFor(); await waitSteps(8)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await pick('纠错包').waitFor(); await waitSteps(8)
  assert.equal(new URL(page.url()).searchParams.get('runId'), 'run-correction-b')
  assert.equal(new URL(page.url()).searchParams.get('stageId'), 'correction')
  await page.locator('.round-node-switch').click()
  await page.waitForURL(/runId=run-correction-a/); await waitSteps(8)
  await chooseRun('run-main')
  await chooseRun('run-extra')
  await page.waitForURL(/runId=run-extra/); await waitSteps(8)
  const onlyResource = pick('分阶测试题')
  assert.equal(await page.locator('.resource-chain-picker > button').count(), 1)
  assert.equal(await onlyResource.getAttribute('aria-pressed'), 'true')
  await resourceAction('查看批次记录')
  assert.equal(await onlyResource.getAttribute('aria-pressed'), 'false')
  await onlyResource.click()
  assert.equal(await onlyResource.getAttribute('aria-pressed'), 'true')
  await waitSteps(8)
  assert.equal(await graph.locator('[data-step-id^="run-main"]').count(), 0)
  checks.push('two nodes, corrections and multiple jobs remain scoped; delayed detail/old SSE cannot populate the new node; single resource remains visible and returns from batch mode')

  await open('run-older'); await pick('实操指南').click(); await waitSteps(10)
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-older / 实操指南 / v1 专属正文。', { exact: true }).waitFor()
  assert.doesNotMatch(await page.getByRole('region', { name: '学习资源预览' }).innerText(), /v2 专属正文/)
  await open('run-legacy'); await waitSteps(4)
  for (const key of ['roundId', 'memberId', 'stageId']) assert.equal(new URL(page.url()).searchParams.has(key), false)
  assert.match(await page.locator('.chain-record-note').innerText(), /缺少明确关联/)
  await resourceAction('查看批次记录'); await waitSteps(5)
  await open('run-empty'); await pick('实操指南').waitFor(); await pick('实操指南').click()
  await graph.getByText('等待本资源的关联执行记录', { exact: true }).waitFor()
  await open('run-no-artifact'); await waitSteps(5)
  assert.match(await node('run-no-artifact', 5).innerText(), /生成失败/)
  checks.push('legacy unlinked records degrade explicitly, queued placeholders and failure without an artifact stay usable')

  await open('run-main'); await pick('讲义').waitFor()
  await chooseRun('run-legacy'); await waitSteps(4)
  for (const key of ['roundId', 'memberId', 'stageId']) assert.equal(new URL(page.url()).searchParams.has(key), false, 'unbound task clears old round query')
  await page.locator('.task-selector .selector-field').nth(1).locator('.el-select').click()
  await page.locator('.el-select-dropdown:visible [data-run-id="run-correction-b"]').click()
  // Change again without waiting for the first Run's hydration to complete.
  await chooseRun('run-main'); await waitSteps(8)
  assert.equal(new URL(page.url()).searchParams.get('memberId'), 'a')
  assert.equal(new URL(page.url()).searchParams.get('stageId'), 'initial')
  assert.equal(await graph.locator('[data-step-id^="run-correction-b"]').count(), 0)
  checks.push('top batch navigation survives correction reload, clears unbound round query and keeps latest rapid selection')

  await open('run-main'); await pick('实操指南').waitFor(); await pick('实操指南').click(); await waitSteps(10)
  for (const viewport of [{ width: 1393, height: 620 }, { width: 375, height: 812 }]) {
    await page.setViewportSize(viewport)
    await page.waitForTimeout(120)
    const geometry = await graph.evaluate(el => {
      const nodes = [...el.querySelectorAll('.execution-graph-node')]
      const seq = nodes.map(n => Number(n.querySelector('.execution-graph-sequence').textContent.replace('STEP ', '')))
      const bounds = el.getBoundingClientRect()
      return { paths: el.querySelectorAll('.execution-graph-edge').length, nodes: nodes.length, seq,
        finitePaths: [...el.querySelectorAll('.execution-graph-edge')].every(p => !/NaN|undefined/.test(p.getAttribute('d'))),
        contained: nodes.every(n => { const r = n.getBoundingClientRect(); return r.left >= bounds.left - 1 && r.right <= bounds.right + 1 }),
        overflow: document.documentElement.scrollWidth > innerWidth + 1 }
    })
    assert.equal(geometry.paths, geometry.nodes - 1)
    assert.equal(geometry.finitePaths, true); assert.equal(geometry.contained, true); assert.equal(geometry.overflow, false)
    assert.deepEqual(geometry.seq, [...geometry.seq].sort((a, b) => b - a))
    await pick('讲义').focus(); await page.keyboard.press('Enter'); await waitSteps(8)
    assert.equal(await pick('讲义').evaluate(el => document.activeElement === el), true)
    const pickerBounds = await pick('讲义').boundingBox(); assert.ok(pickerBounds.height >= (viewport.width < 720 ? 44 : 32))
    await pick('实操指南').click(); await waitSteps(10)
    await showGraph(); await page.screenshot({ path: path.join(evidence, `layout-${viewport.width}x${viewport.height}.png`), fullPage: true })
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reduced = await graph.locator('.execution-graph-node').first().evaluate(el => getComputedStyle(el).transitionDuration)
  assert.ok(reduced.split(',').every(value => parseFloat(value) === 0))
  checks.push('desktop short window and 375px layout: order/curves/containment, keyboard, touch targets and reduced motion')
  assert.deepEqual(audit.errors, []); assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.writes, [])
  summary.status = 'PASS'
} catch (error) {
  summary.status = 'FAIL'; summary.failure = { message: error.message, stack: error.stack }
  if (page) await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  heldTimeline?.()
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
  if (browser) await browser.close()
  for (const list of streams.values()) for (const response of list) response.end()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
console.log(`PASS: ${checks.length} resource workflow browser checks; ${evidence}`)
