import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { createHash } from 'node:crypto'
import { readFileSync, existsSync, statSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = path.resolve(process.env.TEST_RUN_OUTPUT || path.join(frontend, 'tests/test-results/report-history-recovery'))
mkdirSync(evidence, { recursive: true })
const errors = [], unexpected = [], streams = new Set(), checks = []
const profile = { learner_id: 'recovery-learner', learner_type: '测试画像', knowledge_base_id: 'kb', skill_level: '初级', learning_goal: '掌握检索基础' }
const coverage = value => ({ value, status: 'complete', source: 'ordinary_review' })
const qualityBatches = [
  { key: 'batch:2', topic: '检索应用', created_at: '2026-11-13T12:00:00Z',
    summary: { resource_total: 1, coverage: coverage(.5), claim_factual_total: 8, claim_risk_fact_total: 1,
      claim_unverified_subset_rate: { value: .125, status: 'complete', source: 'claim_judge' } },
    items: [{ resource_id: 'quality-2', resource_version: 1, resource_type: '实操指南', coverage: coverage(.5) }] },
  { key: 'batch:1', topic: '检索基础', created_at: '2026-11-12T12:00:00Z',
    summary: { resource_total: 1, coverage: coverage(1), reference_resource_total: 1, reference_value: .05 },
    items: [{ resource_id: 'quality-1', resource_version: 1, resource_type: '讲义', coverage: coverage(1),
      hallucination: { value: .05, status: 'reference', source: 'ordinary_rule_reference' } }] },
]
const round = {
  schema_version: '1.0', round_id: 'round-1', protocol_version: 'learning-round/v1', learner_id: profile.learner_id,
  created_at: '2026-11-13T12:00:00Z', available_actions: ['evaluate', 'next'],
  members: [{ member_id: 'member-1', node_id: 'node-1', node_name: '检索基础', role: 'primary', tier: 1, state: 'completed' }],
  stages: [{ stage_id: 'stage-1', kind: 'initial', ordinal: 0, state: 'completed', members: [{ member_id: 'member-1', node_id: 'node-1', role: 'primary', stage_node_id: 'stage-node-1', state: 'completed', resource_types: ['讲义', '实操指南', '分阶测试题'], job_ids: ['run-1'] }] }],
}
function report(days) {
  return {
    learner_id: profile.learner_id, window: { window_days: days }, report_revision: 'rpt_' + createHash('sha256').update(String(days)).digest('hex'),
    initial_diagnostic: { final_tier: 1, questionnaire_tier: 1 },
    metric_summary: { resource_count: days, feedback_count: 1, average_correct_rate: .83, weak_point_count: 0 },
    radar: { dimensions: ['概念', '应用', '证据'], values: [83, 74, 80], measurement_statuses: ['measured', 'measured', 'measured'] },
    resource_quality_summary: { resource_total: 2, coverage: coverage(.75), reference_resource_total: 1, reference_value: .05 },
    recent_resource_quality: qualityBatches.flatMap(batch => batch.items.map(item => ({
      ...item, learning_node_name: batch.key === 'batch:2' ? '应用节点' : undefined,
    }))),
    resource_quality_batches: qualityBatches,
    learning_node_mastery_map: { nodes: [{ skill_node_id: 'node-1', name: '检索基础', tier: 1, mastery_score: .83, mastery_status: 'learning' }], summary: { total_node_count: 1 } },
    resource_difficulty_curve: { points: [
      { point_type: 'batch_fit', resource_count: 1, difficulty_fit_score: 84, feedback_score: .8, experience_score: 100, subjective_feedback_count: 1 },
      { resource_name: '检索讲义', skill_name: '检索基础', resource_type: '讲义', ordinary_review_score: 90, credibility_score: 90 },
    ], summary: {} },
    learning_path_graph: { nodes: [{ skill_node_id: 'node-1', name: '检索基础', tier: 1, role: 'current', progress_status: 'verification_pending', is_current_batch: true }, { skill_node_id: 'node-2', name: '检索应用', tier: 2, role: 'next', mastery_score: .6 }, { skill_node_id: 'node-3', name: '综合检索', tier: 3, blocked: true, reason_codes: ['TIER_NOT_UNLOCKED'], role: 'challenge' }, ...Array.from({ length: 10 }, (_, i) => ({ skill_node_id: `extra-${i}`, name: `学习节点 ${i + 4}`, tier: i < 2 ? 1 : i < 6 ? 2 : 3, stable_order: i + 1, blocked: i > 3, role: 'prerequisite' }))], edges: [{ source_skill_node_id: 'node-1', target_skill_node_id: 'node-2' }, { source_skill_node_id: 'node-2', target_skill_node_id: 'node-3' }, ...Array.from({ length: 10 }, (_, i) => ({ source_skill_node_id: i < 2 ? 'node-1' : i < 6 ? 'node-2' : 'node-3', target_skill_node_id: `extra-${i}` }))], summary: {} },
    learning_round_summary: round, next_suggestions: ['检索基础', '检索应用', '综合检索'],
  }
}
const journey = {
  learner_id: profile.learner_id, profile,
  current_state: { current_nodes: [{ node_id: 'node-1', knowledge_point_id: 'node-1', name: '检索基础', status: 'completed' }], completed_nodes: [], latest_assessment: { score: .83 }, next_action: '前往学习反馈选择下一步学习方案' },
  rounds: [], learning_rounds: [round], unlinked_events: [{ event_id: 'questionnaire', event_type: 'questionnaire', title: '创建学习方向', description: '问卷已提交', occurred_at: '2026-11-13T11:50:00Z', payload: {} }], total_rounds: 1, next_offset: null,
}
function json(res, data, status = 200) { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)) }
const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    if (req.method !== 'GET') { unexpected.push(req.method + ' ' + url.pathname); return json(res, {}, 405) }
    if (url.pathname === '/api/auth/me') return json(res, { user: { user_id: 'recovery-user', username: 'recovery', display_name: '专项验收' } })
    if (url.pathname === '/api/profiles/') return json(res, { items: [profile], total: 1 })
    if (url.pathname === '/api/knowledge/domains') return json(res, { domains: [{ tracks: [{ track_id: 'kb', name: '检索学习' }] }] })
    // Project evaluations are no longer requested by the learner report.
    if (url.pathname === '/api/learning-history/' + profile.learner_id + '/journey') return json(res, journey)
    if (url.pathname === '/api/report/' + profile.learner_id) return json(res, report(Number(url.searchParams.get('window_days') || 30)))
    if (url.pathname === '/api/report/' + profile.learner_id + '/events') {
      res.writeHead(200, { 'content-type': 'text/event-stream' }); res.write(': connected\n\n')
      streams.add(res); res.on('close', () => streams.delete(res)); return
    }
    unexpected.push(url.pathname); return json(res, {}, 404)
  }
  const candidate = path.resolve(dist, '.' + decodeURIComponent(url.pathname))
  const file = candidate.startsWith(dist + path.sep) && existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, 'index.html')
  res.writeHead(200, { 'content-type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' })[path.extname(file)] || 'application/octet-stream' })
  res.end(readFileSync(file))
})
let browser
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const base = 'http://127.0.0.1:' + server.address().port
  browser = await chromium.launch(browserOptions('REPORT_HISTORY_BROWSER_CHANNEL'))
  for (const reducedMotion of ['no-preference', 'reduce']) {
    const context = await browser.newContext({ viewport: { width: 1651, height: 871 }, reducedMotion })
    await context.addInitScript(() => {
      const createElement = Document.prototype.createElement
      Document.prototype.createElement = function (tag, ...args) {
        if (String(tag).toLowerCase() === 'x-vue-echarts') throw new Error('Custom chart containers are unavailable in this compatibility fixture')
        return createElement.call(this, tag, ...args)
      }
    })
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.stack || error.message))
    page.on('console', message => { if (message.type() === 'error') console.error(message.text()) })
    await page.goto(base + '/learning/history', { waitUntil: 'domcontentloaded' })
    await page.locator('.learning-round-history').waitFor()
    await page.waitForTimeout(350)
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.journey-workspace')).opacity === '1')
    assert.ok((await page.locator('.state-grid article').first().innerText()).includes('检索基础'))
    assert.equal(await page.locator('.journey-chain-item .journey-chain-content .learning-round-history').count(), 1)
    await page.screenshot({ path: path.join(evidence, 'history-' + reducedMotion + '.png'), animations: 'disabled' })
    // Model a scrolled long source page: the next route must not inherit it.
    await page.locator('.history-page').evaluate(element => { element.style.minHeight = '2200px' })
    await page.locator('.content-area').evaluate(element => { element.scrollTop = 500 })
    assert.ok(await page.locator('.content-area').evaluate(element => element.scrollTop > 0))
    await page.evaluate(() => {
      const style = document.createElement('style')
      style.id = 'initial-chart-hidden'
      style.textContent = '.report-mastery-section .chart { display:none !important; }'
      document.head.appendChild(style)
    })
    if (reducedMotion === 'reduce') await page.evaluate(() => {
      window.__restoreReportRAF = window.requestAnimationFrame
      window.requestAnimationFrame = () => 0
    })
    await page.getByRole('button', { name: '学习报告', exact: true }).evaluate(button => button.click())
    await page.waitForFunction(() => document.querySelectorAll('.report-page .chart svg').length === 3, null, { polling: 100 })
    assert.equal(await page.locator('.report-mastery-section .chart').getAttribute('data-chart-state'), 'pending')
    await page.evaluate(() => document.getElementById('initial-chart-hidden').remove())
    await page.waitForFunction(() => document.querySelectorAll('.report-page .chart svg').length === 4, null, { polling: 100 })
    await page.waitForFunction(() => [...document.querySelectorAll('.report-mastery-section svg text')].some(item => item.textContent === '83%'), null, { polling: 100 })
    if (reducedMotion === 'reduce') await page.evaluate(() => { window.requestAnimationFrame = window.__restoreReportRAF })
    assert.equal(await page.locator('.report-page x-vue-echarts').count(), 0)
    assert.ok(await page.locator('.report-page .chart').evaluateAll(items => items.every(item => item.tagName === 'DIV' && item.dataset.chartState === 'ready')))
    await page.waitForFunction(() => document.querySelector('.report-summary-metrics strong')?.textContent === '30')
    await page.waitForTimeout(400)
    const position = await page.locator('.content-area').evaluate(element => ({ scroll: element.scrollTop, top: element.getBoundingClientRect().top, hero: document.querySelector('.report-hero').getBoundingClientRect().top }))
    assert.equal(position.scroll, 0, JSON.stringify(position))
    assert.equal(await page.locator('.content-area').evaluate(el => getComputedStyle(el).scrollSnapType), 'y mandatory')
    const reportViewport = await page.locator('.content-area').boundingBox()
    await page.mouse.move(reportViewport.x + 8, reportViewport.y + reportViewport.height / 2)
    await page.mouse.wheel(0, 550)
    await page.waitForFunction(() => {
      const scroller = document.querySelector('.content-area')
      const section = document.querySelector('.report-radar-slot')
      return Math.abs(section.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 22) <= 2
    })
    await page.locator('.content-area').evaluate(el => el.scrollTo({ top: 0, behavior: 'instant' }))

    assert.ok(position.hero >= position.top, JSON.stringify(position))
    assert.equal(await page.locator('.report-page canvas').count(), 0)
    const drawing = await page.locator('.report-page .chart svg').evaluateAll(items => items.map(svg => ({ width: svg.getBoundingClientRect().width, marks: svg.querySelectorAll('path,rect,line,polyline,circle,text').length })))
    assert.ok(drawing.every(item => item.width > 100 && item.marks > 5), JSON.stringify(drawing))
    await page.locator('.report-window-field .el-select').click()
    await page.getByRole('option', { name: '近 7 天', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.report-summary-metrics strong')?.textContent === '7')
    assert.equal(await page.locator('.report-page .chart svg').count(), 4)
    await page.waitForTimeout(350)
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.report-summary-metrics')).opacity === '1')
    await page.screenshot({ path: path.join(evidence, 'report-' + reducedMotion + '.png'), animations: 'disabled' })
    await page.locator('.report-mastery-section').screenshot({ path: path.join(evidence, 'mastery-' + reducedMotion + '.png') })
    checks.push('Native DIV SVG charts with custom elements blocked, zero-size mount recovery, window refresh and navigation scroll reset; reduced-motion case also suspends initial animation frames: ' + reducedMotion)
    assert.equal(await page.getByText('初始校准：', { exact: false }).count(), 0)
    assert.equal(await page.locator('.round-report-summary').count(), 0)
    assert.equal(await page.getByRole('region', { name: '项目评测结果', exact: true }).count(), 0)
    await page.locator('.report-fit-slot').getByText('普通审核参考', { exact: true }).waitFor()
    await page.locator('.report-fit-slot').getByText('难度匹配度', { exact: true }).first().waitFor()
    await page.locator('.report-fit-slot svg').getByText('最新批次', { exact: true }).waitFor()
    const graph = page.locator('.path-card')
    assert.equal(await graph.locator('svg text').filter({ hasText: /^下一步可选$/ }).count(), 1)
    assert.equal(await graph.getByText('进阶挑战', { exact: true }).count(), 0)
    assert.ok((await graph.locator('.visual-heading small').innerText()).includes('13 个节点'))
    await graph.scrollIntoViewIfNeeded()
    assert.equal(await graph.getByRole('complementary', { name: '学习节点详情' }).count(), 0)
    const endpointClips = () => graph.locator('svg').evaluate(svg =>
      [...svg.querySelectorAll('image')].filter(image => image.getAttribute('href')?.startsWith('data:image/svg+xml,')).map(image => {
        const targetClip = image.closest('g[clip-path]')
        const sourceClip = targetClip?.parentElement.closest('g[clip-path]')
        return [sourceClip, targetClip].map(group => {
          const id = group?.getAttribute('clip-path')?.match(/#([^)]*)/)?.[1]
          return id ? document.getElementById(id)?.querySelector('path')?.getAttribute('d') : null
        })
      }),
    )
    const initialClips = await endpointClips()
    assert.equal(initialClips.length, 12)
    assert.ok(initialClips.every(([source, target]) => source && target && source !== target))
    if (reducedMotion === 'no-preference') {
      await graph.screenshot({ path: path.join(evidence, 'path-initial.png') })
    }
    await graph.locator('svg text').filter({ hasText: /^检索应用$/ }).click()
    assert.equal(await graph.locator('.path-toolbar, .path-node-index').count(), 0)
    const frame = graph.locator('.chart-frame')
    assert.equal(await frame.getByRole('status').textContent(), '检索应用')
    const beforeZoom = await graph.locator('svg').innerHTML()
    await frame.press('+')
    assert.notEqual(await graph.locator('svg').innerHTML(), beforeZoom)
    const zoomedClips = await endpointClips()
    assert.equal(zoomedClips.length, initialClips.length)
    assert.notDeepEqual(zoomedClips, initialClips)
    await graph.locator('.visual-heading').getByRole('button', { name: '复位', exact: true }).click()
    assert.equal(await frame.getByRole('status').textContent(), '检索基础')
    assert.deepEqual(await endpointClips(), initialClips)
    await frame.press('ArrowRight')
    assert.equal(await frame.getByRole('status').textContent(), '检索应用')
    await frame.press('Escape')
    assert.equal(await frame.getByRole('status').textContent(), '检索基础')
    await graph.screenshot({ path: path.join(evidence, 'path-desktop-' + reducedMotion + '.png') })
    const quality = page.getByRole('region', { name: '生成资源质量摘要' })
    const cards = quality.locator('.report-quality-metric')
    const rows = quality.locator('.report-quality-list li strong')
    const filter = quality.locator('.el-select')
    assert.equal(await cards.count(), 3)
    assert.deepEqual(await cards.locator(':scope > span').allTextContents(), [
      '知识覆盖', '普通审核参考幻觉率', '幻觉率（已核验事实子集）',
    ])
    assert.equal(await cards.first().locator('strong').textContent(), '75.0%')
    assert.deepEqual(await rows.allTextContents(), ['应用节点—实操指南', '检索基础—讲义'])
    assert.match(await quality.locator('.report-quality-scope').innerText(), /最近 2 份已发布资源，最多 10 份/)
    await filter.click()
    await page.getByRole('option', { name: /检索应用/ }).click()
    assert.equal(await quality.locator('.report-quality-scope').count(), 0)
    assert.equal(await cards.first().locator('strong').textContent(), '50.0%')
    assert.equal(await cards.nth(1).locator('strong').textContent(), '<5%')
    assert.equal(await cards.last().locator('strong').textContent(), '12.5%')
    assert.match(await cards.last().innerText(), /共核验 8 条事实，其中 1 条/)
    assert.deepEqual(await rows.allTextContents(), ['实操指南'])
    await filter.click()
    await page.getByRole('option', { name: /检索基础/ }).click()
    assert.equal(await cards.first().locator('strong').textContent(), '100.0%')
    assert.equal(await cards.nth(1).locator('strong').textContent(), '<5%')
    assert.equal(await cards.last().locator('strong').textContent(), '—')
    assert.match(await cards.last().innerText(), /÷ 已核验事实数 × 100%/)
    assert.match(await cards.last().innerText(), /暂无可用的完整 Claim 核验结果/)
    assert.match(await quality.locator('.report-quality-list').innerText(), /普通审核参考线 <5%/)
    assert.doesNotMatch(await quality.innerText(), /未校准|待核验|仍待 Claim 核验/)
    assert.deepEqual(await rows.allTextContents(), ['讲义'])
    await filter.click()
    await page.getByRole('option', { name: '全部批次', exact: true }).click()
    assert.equal(await cards.first().locator('strong').textContent(), '75.0%')
    assert.deepEqual(await rows.allTextContents(), ['应用节点—实操指南', '检索基础—讲义'])
    await page.getByRole('option', { name: '全部批次', exact: true }).waitFor({ state: 'hidden' })
    assert.deepEqual(await page.locator('.suggestion-list > span').allTextContents(), ['检索基础', '检索应用', '综合检索'])
    await page.setViewportSize({ width: 1363, height: 871 })
    assert.equal(await quality.locator('.claim-calculation-formula').evaluate(element => element.getClientRects().length), 1)
    await page.locator('.report-ending').screenshot({ path: path.join(evidence, 'quality-' + reducedMotion + '.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await page.locator('.content-area').evaluate(el => getComputedStyle(el).scrollSnapType), 'none')
    await page.waitForTimeout(200)
    assert.ok(await graph.evaluate(element => element.scrollWidth <= element.clientWidth + 1))
    assert.ok(await quality.evaluate(element => element.scrollWidth <= element.clientWidth + 1))
    assert.ok(await page.locator('.suggestion-list').evaluate(element => element.scrollWidth <= element.clientWidth + 1))
    checks.push('Quality summary shows three cards and refreshes metrics and detail rows for each batch and all batches: ' + reducedMotion)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await graph.screenshot({ path: path.join(evidence, 'path-mobile-' + reducedMotion + '.png') })
    await page.setViewportSize({ width: 1651, height: 871 })
    checks.push('Report sections removed without evaluation request; SVG node click, keyboard selection, related paths, zoom/reset, full-width graph without inspector and mobile layout: ' + reducedMotion)
    await page.getByRole('button', { name: '学习历史', exact: true }).click()
    await page.locator('.learning-round-history').waitFor()
    await page.waitForTimeout(350)
    await page.setViewportSize({ width: 390, height: 844 })
    assert.ok(await page.locator('.learning-round-history').evaluate(element => element.scrollWidth <= element.clientWidth + 1))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.screenshot({ path: path.join(evidence, 'history-mobile-' + reducedMotion + '.png') })
    checks.push('Round target, timeline rail and mobile wrapping: ' + reducedMotion)
    await context.close()
  }
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify({ status: 'PASS', evidence_type: 'offline_browser_fixture', checks, errors, unexpected }, null, 2))
  console.log('PASS: report/history recovery (' + checks.length + ' scenarios)')
} finally {
  await browser?.close()
  for (const stream of streams) stream.end()
  await new Promise(resolve => server.close(resolve))
}
