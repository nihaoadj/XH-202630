import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(root, 'dist')
if (!existsSync(path.join(dist, 'index.html'))) throw new Error('run npm --prefix frontend run build before browser test')
let browser
try { browser = await chromium.launch({ headless: true, channel: process.env.LEARNING_REPORT_BROWSER_CHANNEL || 'msedge' }) }
catch (error) { console.log(`learning report browser unavailable: ${error.message.split('\n')[0]} (skipped)`); process.exit(0) }

const report = {
  report_schema_version: '3.0', report_revision: `rpt_${'a'.repeat(64)}`, learner_id: 'learner', generated_at: new Date().toISOString(),
  as_of_profile_version: 1, radar: { dimensions: [], values: [] }, weak_points: [], strong_points: [], skill_level: 'beginner', learning_goal: 'learn', difficulty_curve: [],
  metric_summary: { resource_count: 0, feedback_count: 0, average_correct_rate: null, weak_point_count: 0 },
  learning_activity: { status: 'not_measured', verified_attempt_count: 0, answered_item_count: 0, correct_item_count: 0, verified_accuracy: null, accuracy_delta: null },
  weakness_groups: { verified_weak: [], regressing_learning: [], needs_evidence: [] }, resource_credibility_summary: { total_count: 0, trusted_count: 0 }, recent_resource_credibility: [],
  ability_nodes: [], mastery_summary: {}, weakness_priorities: [], recent_resources: [], recent_feedback: [], next_suggestions: [], window: { window_days: 30 }, freshness: { source_revisions: {} },
  knowledge_blind_spot_map: { schema_version: '1.0', dimensions: [], nodes: [], cells: [], summary: {} },
  resource_difficulty_curve: {
    schema_version: '1.0', strategy_version: 'declared-band/v1',
    points: [{ resource_id: 'resource', skill_node_id: 'node', skill_name: '测试节点', resource_type: '讲义', resource_ids: ['resource'], learner_readiness_score: .6, resource_difficulty_score: .6, difficulty_gap: 0, match_status: 'matched', confidence: 'medium', difficulty_source: 'declared_band', reason_codes: [], credibility_score: 80, credibility_level: 'good', credibility_grade: 'trusted', credibility_score_breakdown: { publication_review_score: 40, source_traceability_score: 50, claim_review_score: 0, claim_review_passed: false, score_ceiling: 80, ceiling_applied: true } }],
    summary: { total_point_count: 1, measured_point_count: 1, credibility_scored_count: 1, average_credibility_score: 80, claim_review_passed_count: 0, claim_ceiling_applied_count: 1 },
  },
  learning_path_graph: { schema_version: '1.0', nodes: [], edges: [], current_node_ids: [], recommended_next_node_ids: [], summary: {} },
}
const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://local')
  const json = value => { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(value)) }
  if (url.pathname === '/api/auth/me') return json({ user: { user_id: 'user', username: 'user', display_name: 'User' } })
  if (url.pathname === '/api/profiles/') return json({ items: [{ learner_id: 'learner', learner_type: '测试', knowledge_base_id: 'kb', skill_level: 'beginner' }] })
  if (url.pathname === '/api/knowledge/domains') return json({ domains: [{ tracks: [{ track_id: 'kb', name: '测试方向' }] }] })
  if (url.pathname === '/api/report/learner/events') { res.setHeader('content-type', 'text/event-stream'); return res.end(`id: ${report.report_revision}\nevent: report_snapshot\ndata: ${JSON.stringify({ learner_id: 'learner', window_days: 30, report_revision: report.report_revision })}\n\n`) }
  if (url.pathname === '/api/report/learner') { res.setHeader('etag', `"${report.report_revision}"`); return json(report) }
  let file = path.join(dist, url.pathname === '/' || url.pathname === '/report' ? 'index.html' : url.pathname)
  if (!file.startsWith(dist) || !existsSync(file)) file = path.join(dist, 'index.html')
  if (file.endsWith('.js')) res.setHeader('content-type', 'text/javascript')
  else if (file.endsWith('.css')) res.setHeader('content-type', 'text/css')
  else if (file.endsWith('.html')) res.setHeader('content-type', 'text/html')
  res.end(readFileSync(file))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
try {
  const port = server.address().port
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.goto(`http://127.0.0.1:${port}/report`, { waitUntil: 'domcontentloaded' })
  await assert.doesNotReject(() => page.getByRole('heading', { name: '学习报告', level: 2 }).waitFor())
  assert.equal(await page.getByRole('heading', { name: '文本资源可信证据' }).count(), 1)
  assert.equal(await page.getByRole('heading', { name: '资源难度匹配曲线' }).count(), 1)
  assert.equal(await page.getByLabel('学习者准备度、资源难度与资源可信度对比曲线').count(), 1)
  await assert.doesNotReject(() => page.getByText('平均可信度 80 / 100 · 已量化 1 · Claim 通过 0 · 受 80 分上限约束 1').waitFor())
  assert.equal(await page.getByRole('heading', { name: '学习路径规划图' }).count(), 1)
  assert.equal(await page.getByRole('combobox', { name: '报告时间窗口' }).count(), 1)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true)
  await page.close()
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)) }
