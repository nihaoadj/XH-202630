// T48 browser verification for the report quality block, against the real
// production build and an isolated loopback fixture (no user backend).
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(root, 'dist')
if (!existsSync(path.join(dist, 'index.html'))) {
  throw new Error('run npm --prefix frontend run build before resource-quality browser test')
}
const quality = JSON.parse(
  readFileSync(path.join(root, 'tests/fixtures/resource-quality-report.json'), 'utf8'),
)

const report = {
  report_schema_version: '4.4', report_revision: `rpt_${'b'.repeat(64)}`,
  learner_id: 'learner', generated_at: new Date().toISOString(), as_of_profile_version: 1,
  radar: { dimensions: [], values: [] }, weak_points: [], strong_points: [],
  skill_level: 'beginner', learning_goal: 'learn', difficulty_curve: [],
  metric_summary: { resource_count: 2, feedback_count: 0, average_correct_rate: null, weak_point_count: 0 },
  learning_activity: {
    status: 'not_measured', verified_attempt_count: 0, answered_item_count: 0,
    correct_item_count: 0, verified_accuracy: null, accuracy_delta: null,
  },
  weakness_groups: { verified_weak: [], regressing_learning: [], needs_evidence: [] },
  resource_credibility_summary: { total_count: 2, trusted_count: 1 },
  recent_resource_credibility: [],
  resource_quality_summary: quality.resource_quality_summary,
  recent_resource_quality: quality.recent_resource_quality,
  ability_nodes: [], mastery_summary: {}, weakness_priorities: [], recent_resources: [],
  recent_feedback: [], next_suggestions: [], window: { window_days: 30 },
  freshness: { source_revisions: {} },
  knowledge_blind_spot_map: { schema_version: '1.0', dimensions: [], nodes: [], cells: [], summary: {} },
  resource_difficulty_curve: {
    schema_version: '1.0', strategy_version: 'declared-band/v1', points: [],
    summary: {
      total_point_count: 0, measured_point_count: 0, credibility_scored_count: 0,
      average_credibility_score: null, claim_review_passed_count: 0,
      claim_ceiling_applied_count: 0,
    },
  },
  learning_path_graph: {
    schema_version: '1.0', nodes: [], edges: [], current_node_ids: [],
    recommended_next_node_ids: [], summary: {},
  },
}

const evaluation = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/resource-quality-evaluation.json'), 'utf8'))
let evaluationMode = 'empty'
let qualityReads = 0
const currentQuality = structuredClone(quality.recent_resource_quality[0])
currentQuality.resource_spec_id = 'spec-quality'
currentQuality.published = false
currentQuality.target_coverage[0].display_name = '检索目标'
currentQuality.target_coverage[0].paragraph_id = 'paragraph-target'
const resource = {
  resource_id: currentQuality.resource_id, resource_spec_id: 'spec-quality', run_id: 'run-quality',
  resource_type: '讲义', representation: 'text', difficulty: '中级', topic: '质量专项',
  content_text: '# 测试资源', knowledge_points: ['node-0'], source_refs: [], version: 1,
  review_id: currentQuality.review_id, publication_status: 'unpublished',
}
const execution = { ...resource, resource_execution_state: 'failed', attempt: 1, display_order: 0 }
const job = {
  run_id: 'run-quality', learner_id: 'learner', batch_id: 'batch-quality', job_status: 'failed',
  request_payload: { learner_id: 'learner', topic: '质量专项', resource_types: ['讲义'], include_review: true, include_claim_check: false },
  resource_executions: [execution], created_at: '2026-11-07T00:00:00Z',
}
const timeline = {
  run: { run_id: 'run-quality', status: 'failed', last_event_sequence: 0 }, events: [], steps: [],
  resource_executions: [execution], resource_versions: [resource], evidence: [], reviews: [],
}

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://local')
  const json = value => {
    res.setHeader('content-type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(value))
  }
  if (url.pathname === '/api/evaluation/summary') {
    if (evaluationMode === 'error') { res.statusCode = 500; return json({ message: 'fixture failure' }) }
    return json({ sample_count: evaluationMode === 'empty' ? 0 : 2, metrics: {}, ablation: [], resource_quality_evaluations: evaluationMode === 'empty' ? [] : [evaluation] })
  }
  if (url.pathname === '/api/generate/jobs') return json({ items: [job] })
  if (url.pathname === '/api/generate/jobs/run-quality') return json(job)
  if (url.pathname === '/api/courseware/jobs') return json({ items: [] })
  if (url.pathname === '/api/skills/nodes') return json({ nodes: [] })
  if (url.pathname === '/api/resources/learner') return json({ resources: [], total: 0 })
  if (url.pathname === '/api/runs/run-quality/timeline') return json(timeline)
  if (url.pathname === '/api/runs/run-quality/claims') return json({ run_id: 'run-quality', claims: [], judgements: [], resource_metrics: {} })
  if (url.pathname === '/api/runs/run-quality/resource-quality') {
    qualityReads += 1
    return json({ run_id: 'run-quality', items: [currentQuality], summary: quality.resource_quality_summary })
  }
  if (url.pathname === '/api/runs/run-quality/events') {
    res.setHeader('content-type', 'text/event-stream')
    return res.end(`event: snapshot\ndata: ${JSON.stringify({run_id: 'run-quality', status: 'failed', is_terminal: true})}\n\n`)
  }
  if (url.pathname === '/api/auth/me') {
    return json({ user: { user_id: 'user', username: 'user', display_name: 'User' } })
  }
  if (url.pathname === '/api/profiles/') {
    return json({ items: [{
      learner_id: 'learner', learner_type: '测试', knowledge_base_id: 'kb', skill_level: 'beginner',
    }] })
  }
  if (url.pathname === '/api/knowledge/domains') {
    return json({ domains: [{ tracks: [{ track_id: 'kb', name: '测试方向' }] }] })
  }
  if (url.pathname === '/api/report/learner/events') {
    res.setHeader('content-type', 'text/event-stream')
    return res.end(
      `id: ${report.report_revision}\nevent: report_snapshot\n`
      + `data: ${JSON.stringify({ learner_id: 'learner', window_days: 30, report_revision: report.report_revision })}\n\n`,
    )
  }
  if (url.pathname === '/api/report/learner') {
    res.setHeader('etag', `"${report.report_revision}"`)
    return json(report)
  }
  let file = path.join(dist, url.pathname === '/' || url.pathname === '/report' ? 'index.html' : url.pathname)
  if (!file.startsWith(dist) || !existsSync(file)) file = path.join(dist, 'index.html')
  if (file.endsWith('.js')) res.setHeader('content-type', 'text/javascript')
  else if (file.endsWith('.css')) res.setHeader('content-type', 'text/css')
  else if (file.endsWith('.html')) res.setHeader('content-type', 'text/html')
  res.end(readFileSync(file))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))

let browser
try {
  browser = await chromium.launch(browserOptions('RESOURCE_QUALITY_BROWSER_CHANNEL'))
  const port = server.address().port
  const viewport = { width: 390, height: 844 }
  const page = await browser.newPage({ viewport })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  const evidenceDir = process.env.TEST_RUN_OUTPUT
    ? path.resolve(process.env.TEST_RUN_OUTPUT)
    : path.join(root, 'tests/test-results/resource-quality')
  mkdirSync(evidenceDir, { recursive: true })
  await page.goto(`http://127.0.0.1:${port}/report`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '学习报告', level: 2 }).waitFor()

  // Summary block: measured 80% is tied to its source and status.
  await page.getByRole('heading', { name: '生成资源质量摘要' }).waitFor()
  const section = page.getByLabel('生成资源质量摘要')
  await section.getByText('80.0%', { exact: true }).first().waitFor()
  assert.match(await section.innerText(), /知识覆盖（当前可见资源聚合）[\s\S]*80\.0%[\s\S]*普通审核 · 已测量/)

  // Reference card: 5% must be visibly "待核验" and must not use success tone.
  const referenceCard = section.locator('.report-quality-metric.is-reference')
  assert.equal(await referenceCard.count(), 1)
  assert.match(await referenceCard.innerText(), /普通审核参考幻觉率[\s\S]*5%[\s\S]*普通审核参考／待核验/)
  assert.equal(await referenceCard.locator('strong.is-success').count(), 0)
  assert.equal(await referenceCard.locator('strong.is-attention').count(), 1)

  // A resource without Claim results shows an em dash plus the reason, never 0%.
  const rows = section.locator('.report-quality-list li')
  assert.equal(await rows.count(), 2)
  const noClaimRow = rows.nth(1)
  assert.match(await noClaimRow.innerText(), /幻觉 —/)
  assert.doesNotMatch(await noClaimRow.innerText(), /幻觉 0\.0%/)
  assert.match(await noClaimRow.innerText(), /未开启 Claim 核验/)

  // Measured reference row stays attention, not success.
  const measuredRow = rows.nth(0)
  assert.match(await measuredRow.innerText(), /覆盖 75\.0%（普通审核 · 已测量）/)
  assert.match(await measuredRow.innerText(), /幻觉 5% · 普通审核参考 · 未校准 · 待核验/)

  const project = page.getByLabel('项目评测结果')
  await project.getByText(/暂无有效的版本化评测记录/).waitFor()
  assert.match(await project.innerText(), /≥90%[\s\S]*<5%[\s\S]*≥85%/)
  evaluationMode = 'valid'
  await page.reload({ waitUntil: 'domcontentloaded' })
  await project.getByRole('heading', { name: /离线计算验证/ }).waitFor()
  assert.match(await project.innerText(), /难度适配准确率：[\s\S]*100.0%/)
  assert.match(await project.innerText(), /不代表正式比赛整体门已通过/)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.setViewportSize({ width: 1440, height: 1000 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: path.join(evidenceDir, 'report-evaluation-desktop.png'), fullPage: true })
  evaluationMode = 'error'
  await page.reload({ waitUntil: 'domcontentloaded' })
  await project.getByRole('alert').waitFor()
  assert.match(await project.innerText(), /不能据此判断达标/)
  assert.equal(await project.getByText('100.0%', { exact: true }).count(), 0)

  // Real GenerateView -> AgentVisualization -> resource card -> audit panel.
  await page.goto(`http://127.0.0.1:${port}/generate`, { waitUntil: 'domcontentloaded' })
  const card = page.locator('.execution-card').first()
  await card.getByText('75.0%', { exact: true }).waitFor()
  assert.match(await card.innerText(), /难度审核：通过/)
  assert.ok(qualityReads > 0, 'failed unpublished run must fetch quality on entry')
  await card.getByRole('button', { name: '查看过程详情' }).click()
  const detail = page.getByRole('dialog', { name: '资源审核详情' })
  await detail.getByLabel('逐知识点定位').waitFor()
  assert.match(await detail.innerText(), /检索目标（node-0）：已覆盖[\s\S]*paragraph-target/)
  assert.match(await detail.innerText(), /事实与证据：通过[\s\S]*自包含性：通过/)
  assert.match(await detail.getByLabel('完整问题账本统计').innerText(), /当前开放 0/)
  const beforeRefresh = qualityReads
  await Promise.all([page.waitForResponse(response => response.url().endsWith('/resource-quality')), detail.getByRole('button', { name: '刷新数据' }).click()])
  await page.waitForFunction(() => !document.querySelector('.audit-loading'))
  assert.ok(qualityReads > beforeRefresh)
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true)
  assert.deepEqual(pageErrors, [])

  await page.screenshot({ path: path.join(evidenceDir, 'generation-quality-phone.png'), fullPage: true })
  writeFileSync(path.join(evidenceDir, 'summary.json'), JSON.stringify({
    status: 'PASS', evidence_type: 'browser_fixture', viewport,
    page_errors: pageErrors,
    checks: [
      '80% aggregate with ordinary-review source',
      '5% reference labelled uncalibrated and not success',
      'em dash for unmeasured Claim',
      'per-resource rows bind to the served item',
      'reduced motion', 'project evaluation empty/valid/error states', 'desktop and phone layout', 'failed unpublished generation card and detail prop chain', 'audit refresh reloads quality',
    ],
  }, null, 2))
  await page.close()
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
console.log('resourceQualityBrowser: PASS')
