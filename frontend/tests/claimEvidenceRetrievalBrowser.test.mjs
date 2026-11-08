// T50 browser verification of the Claim evidence retrieval panel, against the
// real production build and an isolated loopback fixture (no user backend).
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
  throw new Error('run npm --prefix frontend run build before claim evidence retrieval browser test')
}

const runId = 'run-supplement'
const resourceId = 'res-supplement'
const resource = {
  resource_id: resourceId, resource_spec_id: 'spec-supplement', run_id: runId,
  resource_type: '讲义', representation: 'text', difficulty: '中级', topic: '补检专项',
  content_text: '# 测试资源', knowledge_points: ['node-0'], source_refs: [], version: 1,
  review_id: 'review-supplement', publication_status: 'unpublished', review_status: 'approved',
}
const execution = { ...resource, resource_execution_state: 'approved', attempt: 1, display_order: 0 }
const job = {
  run_id: runId, learner_id: 'learner', batch_id: 'batch-supplement', job_status: 'completed',
  request_payload: {
    learner_id: 'learner', topic: '补检专项', resource_types: ['讲义'],
    include_review: true, include_claim_check: true, include_claim_evidence_retrieval: true,
  },
  resource_executions: [execution], created_at: '2026-11-08T00:00:00Z',
}
const claimStep = {
  step_id: 'step-claim', run_id: runId, step_sequence: 6, step_no: 6,
  node_name: 'claim_judge', agent_name: 'claim_judge', action: '独立 Claim 判定',
  status: 'success', input_summary: 'Claim 3 条', output_summary: '支持 2 条；缺证 1 条',
  decision_reason: '按冻结证据判定', resource_ids: [resourceId], evidence_refs: ['ev-base'],
  started_at: '2026-11-08T00:00:00Z', ended_at: '2026-11-08T00:00:02Z',
  duration_ms: 2000, retry_count: 0,
}
const timeline = {
  run: { run_id: runId, status: 'completed', last_event_sequence: 1 }, events: [],
  steps: [claimStep],
  resource_executions: [execution], resource_versions: [resource], evidence: [], reviews: [],
}
const claims = {
  run_id: runId, audit_status: 'complete', claims: [], judgements: [],
  resource_metrics: {
    [resourceId]: {
      metric_status: 'complete', claim_hallucination_rate: 0.0, claim_total: 2,
      factual_claim_total: 2, supported_claim_total: 2, contradicted_claim_total: 0,
      not_in_evidence_claim_total: 0, non_factual_claim_total: 0, incomplete_claim_total: 0,
    },
  },
}

function supplementSummary(mode) {
  const blocked = mode === 'blocked'
  return {
    contract_version: 'claim-evidence-retrieval/v1',
    run_id: runId,
    requested: true,
    status: blocked ? 'blocked' : 'completed',
    reason_code: blocked ? 'contradicted' : null,
    resource_id: resourceId,
    resource_version: 1,
    review_id: 'review-supplement',
    target_claim_total: 1,
    attempted_claim_total: 1,
    remaining_claim_total: 0,
    query_total: 2,
    logical_call_total: 2,
    attempt_total: 2,
    known_tokens: 120,
    unknown_tokens: 0,
    initial_supported_total: 1,
    initial_contradicted_total: 0,
    initial_not_in_evidence_total: 1,
    effective_supported_total: blocked ? 1 : 2,
    effective_contradicted_total: blocked ? 1 : 0,
    effective_not_in_evidence_total: blocked ? 0 : 0,
    factual_claim_total: 2,
    evidence_scope_ids: ['cevs_' + 'a'.repeat(32)],
    sessions: [{
      session_id: 'cers_' + 'b'.repeat(32),
      resource_version: 1,
      status: blocked ? 'blocked' : 'completed',
      reason_code: blocked ? 'contradicted' : null,
      active: !blocked,
      hard_block: blocked,
      target_claim_total: 1,
      attempted_claim_total: 1,
      remaining_claim_total: 0,
      query_total: 2,
      logical_call_total: 2,
      attempt_total: 2,
      known_tokens: 120,
      unknown_tokens: 0,
      evidence_scope_ids: ['cevs_' + 'a'.repeat(32)],
    }],
  }
}

let supplementMode = 'active'

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://local')
  const json = value => {
    res.setHeader('content-type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(value))
  }
  if (url.pathname === '/api/auth/me') return json({ user: { user_id: 'user', username: 'user', display_name: 'User' } })
  if (url.pathname === '/api/profiles/') {
    return json({ items: [{ learner_id: 'learner', learner_type: '测试', knowledge_base_id: 'kb', skill_level: '中级' }] })
  }
  if (url.pathname === '/api/knowledge/domains') return json({ domains: [{ tracks: [{ track_id: 'kb', name: '测试方向' }] }] })
  if (url.pathname === '/api/skills/nodes') return json({ nodes: [] })
  if (url.pathname === '/api/generate/jobs') return json({ items: [job] })
  if (url.pathname === `/api/generate/jobs/${runId}`) return json(job)
  if (url.pathname === '/api/courseware/jobs') return json({ items: [] })
  if (url.pathname === '/api/resources/learner') return json({ resources: [], total: 0 })
  if (url.pathname === `/api/runs/${runId}/timeline`) return json(timeline)
  if (url.pathname === `/api/runs/${runId}/claims`) return json(claims)
  if (url.pathname === `/api/runs/${runId}/claim-evidence-retrieval`) {
    return json(supplementSummary(supplementMode))
  }
  if (url.pathname === `/api/runs/${runId}/resource-quality`) {
    return json({ run_id: runId, items: [], summary: {} })
  }
  if (url.pathname === `/api/runs/${runId}/events`) {
    res.setHeader('content-type', 'text/event-stream')
    return res.end(`event: snapshot\ndata: ${JSON.stringify({ run_id: runId, status: 'completed', is_terminal: true })}\n\n`)
  }
  let file = path.join(dist, url.pathname === '/' ? 'index.html' : url.pathname)
  if (!file.startsWith(dist) || !existsSync(file)) file = path.join(dist, 'index.html')
  if (file.endsWith('.js')) res.setHeader('content-type', 'text/javascript')
  else if (file.endsWith('.css')) res.setHeader('content-type', 'text/css')
  else if (file.endsWith('.html')) res.setHeader('content-type', 'text/html')
  res.end(readFileSync(file))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))

let browser
try {
  browser = await chromium.launch(browserOptions('CLAIM_EVIDENCE_BROWSER_CHANNEL'))
  const port = server.address().port
  const page = await browser.newPage({ viewport: { width: 1393, height: 900 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  const evidenceDir = process.env.TEST_RUN_OUTPUT
    ? path.resolve(process.env.TEST_RUN_OUTPUT)
    : path.join(root, 'tests/test-results/claim-evidence-retrieval')
  mkdirSync(evidenceDir, { recursive: true })

  await page.goto(`http://127.0.0.1:${port}/generate`, { waitUntil: 'domcontentloaded' })
  const claimNode = page.locator('[data-node-key="claim_judge"]')
  await claimNode.waitFor()
  await claimNode.click()
  const detail = page.locator('.workflow-detail-dialog')
  await detail.waitFor()
  const panel = page.getByTestId('claim-evidence-retrieval')
  await panel.waitFor()

  // An activated round is labelled as effective and keeps the first round visible.
  assert.match(await panel.innerText(), /补检完成并已生效/)
  assert.match(await panel.innerText(), /首次缺证 1 条 · 补检后缺证 0 条（事实陈述共 2 条）/)
  assert.match(await panel.innerText(), /补检后（已生效）/)
  assert.match(await panel.innerText(), /目标 1 条 · 已重判 1 条 · 未执行 0 条/)
  assert.equal(await panel.locator('.claim-supplement-block').count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: path.join(evidenceDir, 'supplement-active.png'), fullPage: true })

  // A hard-blocked round must show the publication bar and the reason.
  supplementMode = 'blocked'
  await page.reload({ waitUntil: 'domcontentloaded' })
  await claimNode.click()
  await panel.waitFor()
  assert.match(await panel.innerText(), /补检发现反证或来源冲突/)
  assert.match(await panel.innerText(), /该资源版本因新增反证或来源冲突不得发布，需要修订后重新审核。/)
  assert.match(await panel.innerText(), /首次判定（仍生效）/)
  assert.match(await panel.innerText(), /新增证据与陈述相反/)
  assert.equal(await panel.locator('li.is-blocked').count(), 1)

  // The phone layout keeps the panel readable without horizontal overflow.
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: path.join(evidenceDir, 'supplement-blocked-phone.png'), fullPage: true })
  assert.deepEqual(pageErrors, [])

  writeFileSync(path.join(evidenceDir, 'summary.json'), JSON.stringify({
    status: 'PASS', evidence_type: 'browser_fixture',
    viewport: { width: 1393, height: 900 },
    page_errors: pageErrors,
    checks: [
      'activated round labelled effective with first-round counts',
      'blocked round shows the publication bar, reason and inactive row',
      'phone layout without horizontal overflow',
    ],
  }, null, 2))
  await page.close()
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
console.log('claimEvidenceRetrievalBrowser: PASS')
