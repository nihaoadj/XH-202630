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
let conciseSummary = false
let conciseResults = false
let submitted = false
let corrected = false
let gradingReads = 0
let recoveryMode = false
let alignmentMode = false
let recoveryExpired = false
let retakeSession = false
let retakeSubmitted = false
let recovered = false
const member = (index, extra = {}) => ({ member_id: `m${index}`, node_id: `n${index}`, role: legacy ? 'legacy' : index === 1 ? 'primary' : 'review', node_name: index === 1 ? '检索主节点' : '证据复习节点', state: 'awaiting_assessment', ...extra })
const mapping = (index, correction = false) => ({ ...member(index), stage_node_id: `sn${index}`, job_ids: [`run-${correction ? 'correction-' : ''}${index}`], resource_types: correction ? ['纠错包', '分阶测试题'] : index === 1 ? ['讲义', '分阶测试题'] : ['复习清单', '分阶测试题'], resource_ids: [], batch_id: `batch-${index}`, difficulty: index === 1 ? '中级' : '初级' })
const detail = () => ({ schema_version: '1.0', round_id: 'round-1', learner_id: learnerId, protocol_version: legacy ? 'legacy-correction/v1' : 'learning-round/v1', created_at: '2026-11-01T00:00:00Z', members: [member(1), member(2)], stages: [{ stage_id: 'stage-0', kind: 'initial', ordinal: 0, state: 'awaiting_assessment', members: [mapping(1), mapping(2)] }, ...(corrected ? [{ stage_id: 'stage-1', kind: 'correction', ordinal: 1, state: 'awaiting_assessment', members: [mapping(1, true), mapping(2, true)] }] : [])], available_actions: ['evaluate', 'correct', 'next', ...(legacy ? [] : ['append_primary'])] })
const question = index => ({ question_id: `q${index}`, question_type: 'short_answer', question: `描述节点 ${index} 的证据依据`, options: [], skill_node_id: `n${index}`, knowledge_point: `节点${index}`, difficulty: '中级', source: 'resource' })
const session = () => ({ schema_version: '1.0', round_id: 'round-1', stage_id: 'stage-0', session_id: 'session-1', manifest_hash: 'a'.repeat(64), groups: [1, 2].map(index => ({ ...member(index), questions: alignmentMode ? Array.from({length:6}, (_,i) => ({...question(index),question_id:`q${index}-${i}`,question:`第${i+1}题：${question(index).question}`})) : [question(index)] })) })
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
    if (p === `/api/feedback/results/${learnerId}`) return json(res, submitted ? [1,2].map(index => ({
      attempt: { attempt_id: `attempt-node-${index}` },
      analysis: { analysis_status: 'llm', summary: `节点${index}的学习小结。`.repeat(index === 1 ? (conciseSummary ? 12 : 100) : 2), reflection_insight: '本轮重点需要继续巩固。', learner_suggestions: ['回顾简答题的标准答案，补足关键细节。', '尝试分步骤展开回答，减少要点缺失。', '结合材料内容，梳理证据与结论之间的联系。'] },
      feedback_report: { total_score: index === 1 ? 40 : 20, max_score: 100, question_results: Array.from({length:conciseResults ? 6 : 30}, (_,i) => ({question_id:`result-${index}-${i}`,knowledge_point:`节点${index}`,skill_node_id:`n${index}`,question_type:'short_answer',correct:false,score:0,max_score:10})) },
    })) : [])
    if (p === '/api/feedback/rounds/round-1') return json(res, detail())
    if (p === '/api/feedback/rounds/round-1/candidates') return json(res, {
      profile_version: 2,
      generation_options: {
        tier_progress: { active_tier: 2 },
        learn_new_knowledge: [{ skill_node_id: 'n3', name: '下一轮主节点', tier: 2 }],
        learning_candidates: [{ skill_node_id: 'foundation', name: '基础前置', tier: 1 }],
      },
      eligible_review_nodes: [{ skill_node_id: 'n2', name: '证据复习节点', tier: 1 }],
      correction_targets: [1, 2].map(index => ({ node_id: `n${index}`, source_attempt_id: `attempt-node-${index}` })),
      ...(retakeSubmitted ? { remediation_recommendation: {
        kind: 'downgrade',
        node: { skill_node_id: 'foundation', name: '基础前置', tier: 1 },
        original_node_id: 'n1', original_node_name: '检索主节点',
      } } : {}),
    })
    if (p.endsWith('/evaluation-session')) {
      if (body?.retake_from_session_id === 'session-1') retakeSession = true
      return json(res, retakeSession ? { ...session(), session_id: 'session-2' } : session())
    }
    if (p.endsWith('/result')) {
      if (retakeSession) return json(res, retakeSubmitted
        ? { ...feedback(), session_id: 'session-2', attempt_id: 'attempt-retake', profile_version: 3 }
        : { state: 'not_submitted', round_id: 'round-1', stage_id: 'stage-0' })
      if (!submitted) return json(res, { state: 'not_submitted', round_id: 'round-1', stage_id: 'stage-0' })
      if (recoveryMode && !recovered) return recoveryExpired
        ? json(res, { state: 'not_submitted', round_id: 'round-1', stage_id: 'stage-0' })
        : json(res, { state: 'grading', session_id: 'session-1', retry_after_seconds: 2 }, 202)
      if (++gradingReads === 1) return json(res, { state: 'grading', attempt_id: 'attempt-joint' }, 202)
      return json(res, feedback())
    }
    if (p.endsWith('/attempts')) {
      if (retakeSession) {
        retakeSubmitted = true
        return json(res, { ...feedback(), session_id: 'session-2', attempt_id: 'attempt-retake', profile_version: 3 })
      }
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
  const review = page.locator('.round-node-switch')
  await review.focus(); await page.keyboard.press('Enter')
  await page.waitForURL(/runId=run-2/)
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-2-body').waitFor()
  assert.equal(await review.innerText(), '附带复习')
  assert.ok(audit.requests.some(entry => entry.path === '/api/runs/run-2/timeline'))
  assert.equal(await page.getByRole('region', { name: '学习资源预览' }).getByText('run-1-body').count(), 0)
  assert.equal((await page.locator('.status-action-append').innerText()).trim(), '追加资源')
  await page.screenshot({ path: path.join(evidence, 'desktop-two-members.png'), fullPage: true })
  result.checks.push('Real generation page switches Run, trace and resource scope by unique memberId; keyboard and primary append label')
  alignmentMode = true
  for (const width of [1651,390]) {
    await page.setViewportSize({width,height:871})
    await page.goto(`${base}/feedback?learnerId=${learnerId}&roundId=round-1&stageId=stage-0`, {waitUntil:'domcontentloaded'})
    await page.waitForFunction(() => document.querySelectorAll('.round-feedback-workspace .question-card').length === 12)
    await page.getByRole('button',{name:'开始测评',exact:true}).click()
    await page.evaluate(async () => {for(let i=0;i<50;i++) await new Promise(requestAnimationFrame)})
    const measure = () => page.locator('.round-feedback-workspace .feedback-workspace').evaluate(el => {
      const left=el.querySelector('.evaluation-panel').getBoundingClientRect().toJSON()
      const panel=el.querySelector('.reflection-panel'),right=panel.getBoundingClientRect().toJSON()
      return {left,right,client:panel.clientHeight,scroll:panel.scrollHeight,overflow:getComputedStyle(panel).overflowY}
    })
    const top=await measure()
    if(width>960) {
      assert.ok(Math.abs(top.left.top-top.right.top)<=1,JSON.stringify({top}))
      assert.ok(top.scroll<=top.client+1 && !['auto','scroll'].includes(top.overflow),'reflection must not have an inner scroll container')
      await page.screenshot({path:path.join(evidence,'round-reflection-top-1651.png'),animations:'disabled'})
      await page.locator('.content-area').evaluate(el => el.scrollTo({top:el.scrollHeight/2,behavior:'instant'}))
      await page.evaluate(async () => {for(let i=0;i<3;i++) await new Promise(requestAnimationFrame)})
      const middle=await measure()
      assert.ok(middle.scroll<=middle.client+1 && middle.right.top>=40 && middle.right.bottom<=871,'sticky reflection should stay fully visible without inner scrolling')
      await page.locator('.content-area').evaluate(el => el.scrollTo({top:el.scrollHeight,behavior:'instant'}))
      await page.evaluate(async () => {for(let i=0;i<3;i++) await new Promise(requestAnimationFrame)})
      const bottom=await measure()
      assert.ok(Math.abs(bottom.left.bottom-bottom.right.bottom)<=1,JSON.stringify({bottom}))
      await page.screenshot({path:path.join(evidence,'round-reflection-bottom-1651.png'),animations:'disabled'})
      writeFileSync(path.join(evidence,'reflection-alignment.json'),JSON.stringify({top,middle,bottom},null,2))
    } else {
      assert.ok(top.right.top>=top.left.bottom,'mobile reflection stays below questions')
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth),true)
    }
  }
  assert.equal(audit.writes.filter(item => /\/(attempts|corrections|select)$/.test(item.path)).length,0,'alignment checks must not submit answers or select a learning route')
  alignmentMode=false
  await page.setViewportSize({width:1393,height:1000})
  result.checks.push('Round reflection has no inner scroll; desktop start and bottom edges align with long groups; mobile remains stacked')
  await page.goto(`${base}/feedback?learnerId=${learnerId}&roundId=round-1&stageId=stage-0`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: '检索主节点 第 1 题答案' }).fill('检索依据')
  const evaluationBounds = await page.locator('.round-feedback-workspace .evaluation-panel').boundingBox()
  const reflectionBounds = await page.locator('.round-feedback-workspace .reflection-panel').boundingBox()
  assert.ok(evaluationBounds.x < reflectionBounds.x && Math.abs(evaluationBounds.y-reflectionBounds.y)<2, 'round branch reuses aligned two-column layout')
  assert.equal(await page.getByText('最有帮助的内容', {exact:true}).count(),0)
  await page.getByPlaceholder('可以说明你期待下一轮更强化哪些内容，例如增加案例、练习或提高难度。').fill('轮次反思应完整提交')
  await page.locator('.round-feedback-workspace .question-type-tag').first().waitFor({state:'visible'})
  assert.equal(await page.locator('.round-feedback-workspace .question-knowledge-tag').first().innerText(), '节点1')
  await page.screenshot({path:path.join(evidence,'round-assessment-shared-desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true)
  await page.screenshot({path:path.join(evidence,'round-assessment-shared-mobile.png'),fullPage:true})
  await page.setViewportSize({width:1393,height:1000})
  assert.equal(await page.getByRole('button', { name: '需要提示' }).count(), 0)
  assert.equal(await page.locator('.tutor-panel').count(), 0)
  assert.equal(await page.getByRole('button', { name: '统一提交本次测评' }).isDisabled(), true)
  await page.getByRole('textbox', { name: '证据复习节点 第 1 题答案' }).fill('来源核验')
  await page.getByRole('button', { name: '统一提交本次测评' }).click()
  await page.getByRole('region', { name: '各节点独立测评结果' }).getByText('40 分').waitFor()
  await page.getByText('20 分', { exact: true }).waitFor()
  await page.locator('.analysis-content').getByText(/节点1的学习小结/).waitFor()
  await page.locator('.analysis-summary').getByText('AI 分析', { exact: true }).waitFor()
  const verdict = page.locator('.round-feedback-result .next-step-verdict')
  await verdict.getByText('节点 1 仍需补救', { exact: true }).waitFor()
  await page.getByRole('button', { name: /附带复习.*20 分/ }).click()
  assert.equal(await verdict.locator('.round-recommendation-reason').innerText(), '节点 1 仍需补救')
  await page.getByRole('button', { name: /主学习.*40 分/ }).click()
  assert.equal(await page.locator('.batch-selected-label .batch-status').innerText(), '已反馈')
  const regions = await page.locator('.analysis-content, .question-results-content').evaluateAll(items => items.map(el => ({height:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY})))
  assert.ok(regions.every(el => el.scroll > el.height && el.overflow === 'auto'), 'long AI summary and 30 results scroll inside fixed panels')
  await page.screenshot({path:path.join(evidence,'round-result-shared-desktop.png'),fullPage:true})
  conciseSummary = true
  await page.setViewportSize({ width: 1651, height: 871 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  const conciseAnalysis = page.locator('.analysis-summary .analysis-content')
  await conciseAnalysis.waitFor({ state: 'visible' })
  const conciseSummaryBounds = await conciseAnalysis.evaluate(element => ({ client: element.clientHeight, scroll: element.scrollHeight }))
  assert.ok(conciseSummaryBounds.scroll <= conciseSummaryBounds.client + 1,
    `a regular AI summary and suggestions fit without inner scrolling at 1651x871: ${JSON.stringify(conciseSummaryBounds)}`)
  result.checks.push('A regular AI summary, reflection and three suggestions fit without inner scrolling at 1651x871')
  conciseResults = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  const resultList = page.locator('.round-feedback-result .question-results-content .capability-result-list')
  await resultList.waitFor({ state: 'visible' })
  const resultListAlignment = await page.locator('.round-feedback-result .question-results-content').evaluate(area => {
    const list = area.querySelector('.capability-result-list')
    const areaRect = area.getBoundingClientRect()
    const listRect = list.getBoundingClientRect()
    return {
      count: list.querySelectorAll('li').length,
      areaCenter: (areaRect.top + areaRect.bottom) / 2,
      listCenter: (listRect.top + listRect.bottom) / 2,
      areaHeight: area.clientHeight,
      listHeight: listRect.height,
    }
  })
  assert.equal(resultListAlignment.count, 6, `short result fixture has six cards: ${JSON.stringify(resultListAlignment)}`)
  assert.ok(resultListAlignment.listHeight < resultListAlignment.areaHeight
    && Math.abs(resultListAlignment.areaCenter - resultListAlignment.listCenter) <= 1,
  `short result list is centered within its panel: ${JSON.stringify(resultListAlignment)}`)
  await page.screenshot({ path: path.join(evidence, 'round-results-centered-1651x871.png'), fullPage: true })
  result.checks.push('A short question-result list is vertically centered in its available panel space')
  await page.setViewportSize({ width: 1393, height: 1000 })
  const routeSwitch = page.getByRole('switch', { name: '纠错巩固', exact: true })
  const routeHeights = () => page.evaluate(() => {
    const measure = selector => {
      const element = document.querySelector(selector)
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return { height: +rect.height.toFixed(1), top: +rect.top.toFixed(1), bottom: +rect.bottom.toFixed(1) }
    }
    return {
      details: measure('.round-feedback-result .result-details'),
      analysis: measure('.round-feedback-result .analysis-summary'),
      questions: measure('.round-feedback-result .capability-result-panel'),
      panel: measure('.round-feedback-result .next-step-panel'),
    }
  })
  const correctionAlignment = () => page.evaluate(() => {
    const center = selector => {
      const rect = document.querySelector(selector)?.getBoundingClientRect()
      return rect ? (rect.top + rect.bottom) / 2 : null
    }
    const pane = document.querySelector('.round-correction-pane')
    return {
      routeSwitchCenter: center('.round-route-switch'),
      generateButtonCenter: center('.round-correction-submit'),
      flowSteps: pane?.querySelectorAll('.round-correction-step[role="listitem"]').length ?? 0,
      flowWidth: pane?.querySelector('.round-correction-flow')?.getBoundingClientRect().width ?? 0,
      paneWidth: pane?.getBoundingClientRect().width ?? 0,
      paneScrollWidth: pane?.scrollWidth ?? 0,
    }
  })
  assert.equal(await routeSwitch.getAttribute('aria-checked'), 'true')
  const correctionHeights = await routeHeights()
  const correctionActionLayout = await correctionAlignment()
  assert.ok(Math.abs(correctionActionLayout.routeSwitchCenter - correctionActionLayout.generateButtonCenter) <= 3,
    `correction action aligns with the route toggle: ${JSON.stringify(correctionActionLayout)}`)
  assert.ok(correctionActionLayout.flowSteps === 3 && correctionActionLayout.flowWidth > 0
    && correctionActionLayout.paneScrollWidth <= correctionActionLayout.paneWidth + 1,
  `correction route shows its three-step flow without horizontal overflow: ${JSON.stringify(correctionActionLayout)}`)
  const correctionVisual = await page.evaluate(() => {
    const pane = document.querySelector('.round-correction-pane')
    const heading = document.querySelector('.next-step-heading')
    const title = heading?.querySelector('h2')
    const symbol = heading?.querySelector('.review-section-symbol')
    const button = pane?.querySelector('.round-correction-submit')
    const stepTitle = pane?.querySelector('.round-correction-step-copy strong')
    const stepDescription = pane?.querySelector('.round-correction-step-copy small')
    const sequenceTag = pane?.querySelector('.round-correction-sequence-tag')
    const center = element => {
      const rect = element?.getBoundingClientRect()
      return rect ? (rect.top + rect.bottom) / 2 : null
    }
    const buttonStyle = button ? getComputedStyle(button) : null
    return {
      paneBackground: pane ? getComputedStyle(pane).backgroundColor : null,
      paneBackgroundImage: pane ? getComputedStyle(pane).backgroundImage : null,
      paneOverflow: pane ? getComputedStyle(pane).overflow : null,
      panePaddingLeft: pane ? parseFloat(getComputedStyle(pane).paddingLeft) : 0,
      title: title?.innerText || '',
      headingAlignItems: heading ? getComputedStyle(heading).alignItems : '',
      titleCenter: center(title),
      symbolCenter: center(symbol),
      buttonRadius: buttonStyle?.borderRadius || '',
      buttonMinWidth: buttonStyle?.minWidth || '',
      buttonIconCount: button?.querySelectorAll('.el-icon').length ?? 0,
      stepTitleFontSize: stepTitle ? getComputedStyle(stepTitle).fontSize : '',
      stepDescriptionFontSize: stepDescription ? getComputedStyle(stepDescription).fontSize : '',
      sequenceTag: sequenceTag?.textContent.replace(/\s+/g, ' ').trim() || '',
    }
  })
  assert.equal(correctionVisual.paneBackground, 'rgb(255, 255, 255)')
  assert.equal(correctionVisual.paneBackgroundImage, 'none')
  assert.equal(correctionVisual.paneOverflow, 'visible')
  assert.ok(correctionVisual.panePaddingLeft >= 10, `correction heading has a safe inset: ${JSON.stringify(correctionVisual)}`)
  assert.equal(correctionVisual.title, '下一步方案')
  assert.equal(correctionVisual.headingAlignItems, 'center')
  assert.ok(Math.abs(correctionVisual.titleCenter - correctionVisual.symbolCenter) <= 1,
    `route heading icon and text are vertically aligned: ${JSON.stringify(correctionVisual)}`)
  assert.ok(correctionVisual.buttonRadius === '12px' && correctionVisual.buttonMinWidth === '284px'
    && correctionVisual.buttonIconCount === 2,
  `correction action uses the new primary-button treatment: ${JSON.stringify(correctionVisual)}`)
  assert.ok(correctionVisual.stepTitleFontSize === '12px' && correctionVisual.stepDescriptionFontSize === '11px'
    && correctionVisual.sequenceTag === 'CORRECTION LOOP',
  `correction flow keeps its step labels readable and concise: ${JSON.stringify(correctionVisual)}`)
  await page.locator('.round-feedback-result').screenshot({ path: path.join(evidence, 'route-correction.png'), animations: 'disabled' })
  await routeSwitch.click()
  assert.equal(await routeSwitch.getAttribute('aria-checked'), 'false')
  const learningHeights = await routeHeights()
  await page.locator('.round-feedback-result').screenshot({ path: path.join(evidence, 'route-learning.png'), animations: 'disabled' })
  const stableKeys = ['details', 'analysis', 'questions', 'panel']
  assert.ok(stableKeys.every(key => Math.abs(learningHeights[key].height - correctionHeights[key].height) <= 1),
    `route switch must not resize review panels: ${JSON.stringify({ correctionHeights, learningHeights })}`)
  assert.ok(Math.abs(learningHeights.details.height - 458.5) <= 1,
    `review cards keep the rebalanced height at 1393x1000: ${learningHeights.details.height}`)
  for (const size of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
    await page.setViewportSize(size)
    const learning = await routeHeights()
    await routeSwitch.click()
    const corrected = await routeHeights()
    const correctedAlignment = await correctionAlignment()
    assert.ok(Math.abs(correctedAlignment.routeSwitchCenter - correctedAlignment.generateButtonCenter) <= 3,
      `correction action stays aligned at ${size.width}x${size.height}: ${JSON.stringify(correctedAlignment)}`)
    assert.ok(Math.abs(learning.details.height - corrected.details.height) <= 1
      && Math.abs(learning.panel.height - corrected.panel.height) <= 1,
      `route switch must keep heights at ${size.width}x${size.height}: ${JSON.stringify({ learning, corrected })}`)
    await routeSwitch.click()
  }
  writeFileSync(path.join(evidence, 'route-heights.json'), JSON.stringify({ correctionHeights, learningHeights }, null, 2))
  await page.setViewportSize({ width: 1393, height: 1000 })
  const nextChoice = page.getByRole('region', { name: '选择下一轮学习目标' })
  const primaryNodeSelect = nextChoice.getByRole('combobox', { name: '主节点', exact:true })
  await primaryNodeSelect.waitFor()
  assert.equal(await nextChoice.getByRole('radiogroup', { name: '主节点学习方式' }).count(), 0)
  assert.match(await nextChoice.locator('.next-round-field .el-select').first().innerText(), /基础前置/)
  for (const [label, select] of [
    ['主节点', primaryNodeSelect],
    ['副节点', nextChoice.getByRole('combobox', { name: '副节点', exact:true })],
  ]) {
    await select.focus()
    await page.keyboard.press('ArrowDown')
    const dropdown = page.locator('.feedback-node-dropdown.el-popper:visible').last()
    await dropdown.waitFor({ state: 'visible' })
    const selectWidth = await select.evaluate(element => element.closest('.el-select').getBoundingClientRect().width)
    const dropdownWidth = (await dropdown.boundingBox()).width
    const widthDetails = await select.evaluate(element => {
      const root = element.closest('.el-select')
      const wrapper = root.querySelector('.el-select__wrapper')
      const rect = target => {
        const box = target.getBoundingClientRect()
        return { width: box.width, offsetWidth: target.offsetWidth, boxSizing: getComputedStyle(target).boxSizing }
      }
      return { root: rect(root), wrapper: rect(wrapper), input: rect(element) }
    })
    const popupDetails = await dropdown.evaluate(element => ({
      rect: element.getBoundingClientRect().width,
      offsetWidth: element.offsetWidth,
      style: element.getAttribute('style'),
      children: [...element.children].map(child => ({ className: child.className, width: child.getBoundingClientRect().width, style: child.getAttribute('style') })),
    }))
    assert.ok(Math.abs(selectWidth - dropdownWidth) <= 2,
      `${label} dropdown matches its selector width: ${JSON.stringify({ selectWidth, dropdownWidth, widthDetails, popupDetails })}`)
    const focusStyle = await select.evaluate(element => {
      const root = element.closest('.el-select')
      const caret = root.querySelector('.el-select__caret')
      const caretStyle = getComputedStyle(caret)
      return {
        accent: getComputedStyle(root).getPropertyValue('--select-accent').trim(),
        caretBackground: caretStyle.backgroundColor,
        caretColor: caretStyle.color,
      }
    })
    assert.deepEqual(focusStyle, {
      accent: '#3569a6',
      caretBackground: 'rgb(234, 242, 253)',
      caretColor: 'rgb(69, 110, 159)',
    }, `${label} focus state stays in the blue palette: ${JSON.stringify(focusStyle)}`)
    const selectedOption = dropdown.locator('.el-select-dropdown__item.is-selected').first()
    await selectedOption.waitFor({ state: 'visible' })
    const selectedStyle = await selectedOption.evaluate(element => ({
      fontWeight: getComputedStyle(element).fontWeight,
      markerDisplay: getComputedStyle(element, '::before').display,
      markerContent: getComputedStyle(element, '::before').content,
    }))
    assert.equal(selectedStyle.fontWeight, '400', `${label} selected option uses regular weight: ${JSON.stringify(selectedStyle)}`)
    assert.ok(selectedStyle.markerDisplay === 'none' || selectedStyle.markerContent === 'none',
      `${label} selected option has no leading check mark: ${JSON.stringify(selectedStyle)}`)
    await page.keyboard.press('Escape')
  }
  result.checks.push('Primary and review dropdowns match their selector widths and selected options have no leading marker or bold weight')
  result.checks.push('Focused route selectors use the page blue palette')
  const alignment = await page.evaluate(() => {
    const rect = selector => document.querySelector(selector)?.getBoundingClientRect()
    const summaryHeader = rect('.analysis-summary .review-section-heading')
    const questionsHeader = rect('.capability-result-panel .questions-section-heading')
    const questionsCopy = rect('.capability-result-panel .questions-heading-copy')
    const scoreCard = rect('.capability-result-panel .result-score')
    const nextStepHeading = rect('.next-step-heading')
    const nextStepTitle = rect('.next-step-heading h2')
    const nextStepSymbol = rect('.next-step-heading .review-section-symbol')
    const primaryLabel = rect('.next-round-maps > .next-round-field > span')
    const routeSwitch = rect('.round-route-switch')
    const claimRow = rect('.next-round-actions .round-claim-switches')
    return {
      summaryHeaderBottom: summaryHeader?.bottom,
      questionsHeaderBottom: questionsHeader?.bottom,
      questionsCopyCenter: questionsCopy ? (questionsCopy.top + questionsCopy.bottom) / 2 : null,
      scoreCardCenter: scoreCard ? (scoreCard.top + scoreCard.bottom) / 2 : null,
      nextStepHeadingTop: nextStepHeading?.top,
      nextStepTitleCenter: nextStepTitle ? (nextStepTitle.top + nextStepTitle.bottom) / 2 : null,
      nextStepSymbolCenter: nextStepSymbol ? (nextStepSymbol.top + nextStepSymbol.bottom) / 2 : null,
      primaryLabelTop: primaryLabel?.top,
      routeSwitchCenter: routeSwitch ? (routeSwitch.top + routeSwitch.bottom) / 2 : null,
      claimRowCenter: claimRow ? (claimRow.top + claimRow.bottom) / 2 : null,
    }
  })
  assert.ok(Math.abs(alignment.summaryHeaderBottom - alignment.questionsHeaderBottom) <= 1,
    `summary and question header rules align: ${JSON.stringify(alignment)}`)
  assert.ok(Math.abs(alignment.questionsCopyCenter - alignment.scoreCardCenter) <= 1,
    `question heading stays centered beside score: ${JSON.stringify(alignment)}`)
  assert.ok(Math.abs(alignment.nextStepHeadingTop - alignment.primaryLabelTop) <= 1
    && Math.abs(alignment.nextStepTitleCenter - alignment.nextStepSymbolCenter) <= 1,
  `route heading aligns with the node selector and centers its icon with the title: ${JSON.stringify(alignment)}`)
  assert.ok(Math.abs(alignment.routeSwitchCenter - alignment.claimRowCenter) <= 2,
    `route switch and claim row align: ${JSON.stringify(alignment)}`)
  const planLayout = await page.locator('.round-feedback-result .next-step-panel').evaluate(panel => {
    const content = panel.querySelector('.round-route-content')
    const heading = panel.querySelector('.next-step-copy')
    const contentBottom = Math.max(content.getBoundingClientRect().bottom, heading.getBoundingClientRect().bottom)
    return { bottomGap: panel.getBoundingClientRect().bottom - contentBottom, overflow: getComputedStyle(content).overflowY }
  })
  assert.ok(planLayout.bottomGap < 28 && planLayout.overflow === 'visible', JSON.stringify(planLayout))
  const resources = nextChoice.getByRole('group', { name: '主节点资源' })
  await resources.getByText('理解概念，建立知识框架').waitFor()
  const lecture = resources.getByRole('checkbox', { name: '讲义', exact: true })
  const lectureCard = resources.getByText('讲义', { exact: true })
  await lectureCard.click()
  assert.equal(await lecture.isChecked(), false)
  await lectureCard.click()
  assert.equal(await lecture.isChecked(), true)
  await page.setViewportSize({ width: 1651, height: 871 })
  const resourceGeometry = await nextChoice.locator('.next-round-resources > .el-checkbox').evaluateAll(items => items.map(item => {
    const rect = item.getBoundingClientRect()
    const indicator = item.querySelector('.el-checkbox__inner')
    const indicatorStyle = getComputedStyle(indicator)
    const tick = getComputedStyle(indicator, '::after')
    return {
      width: rect.width,
      height: rect.height,
      indicatorWidth: parseFloat(indicatorStyle.width),
      indicatorHeight: parseFloat(indicatorStyle.height),
      indicatorRadius: indicatorStyle.borderRadius,
      indicatorClientWidth: indicator.clientWidth,
      indicatorClientHeight: indicator.clientHeight,
      tickLeft: parseFloat(tick.left),
      tickTop: parseFloat(tick.top),
      tickWidth: parseFloat(tick.width),
      tickHeight: parseFloat(tick.height),
      tickClipPath: tick.clipPath,
      tickTransform: tick.transform,
      tickTransformOrigin: tick.transformOrigin.split(' ').map(parseFloat),
    }
  }))
  assert.ok(resourceGeometry.every(item => Math.abs(item.width - resourceGeometry[0].width) <= 1 && Math.abs(item.height - resourceGeometry[0].height) <= 1),
    `resource cards use uniform dimensions: ${JSON.stringify(resourceGeometry)}`)
  assert.ok(resourceGeometry.every(item => item.indicatorWidth === 20 && item.indicatorHeight === 20 && item.indicatorRadius === '50%'),
    `resource selection indicators are consistently centered circles: ${JSON.stringify(resourceGeometry)}`)
  assert.ok(resourceGeometry.every(item => Math.abs(item.tickLeft - item.indicatorClientWidth / 2) <= 0.5
    && Math.abs(item.tickTop - item.indicatorClientHeight / 2) <= 0.5
    && Math.abs(item.tickTransformOrigin[0] - item.tickWidth / 2) <= 0.5
    && Math.abs(item.tickTransformOrigin[1] - item.tickHeight / 2) <= 0.5
    && item.tickWidth === 9 && item.tickHeight === 9 && item.tickClipPath !== 'none'
    && item.tickTransform !== 'none'),
  `resource check marks are anchored to the center of their circles: ${JSON.stringify(resourceGeometry)}`)
  await page.screenshot({path:path.join(evidence,'round-next-step-desktop.png'),fullPage:true})
  await routeSwitch.click()
  const correctionWideAlignment = await correctionAlignment()
  assert.ok(Math.abs(correctionWideAlignment.routeSwitchCenter - correctionWideAlignment.generateButtonCenter) <= 3,
    `correction action aligns at 1651x871: ${JSON.stringify(correctionWideAlignment)}`)
  await page.locator('.round-feedback-result').screenshot({ path: path.join(evidence, 'route-correction-1651x871.png'), animations: 'disabled' })
  await routeSwitch.click()
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.locator('.round-feedback-result .next-step-panel').evaluate(panel => panel.scrollWidth <= panel.clientWidth + 1), true)
  await page.screenshot({path:path.join(evidence,'round-next-step-mobile.png'),fullPage:true})
  await routeSwitch.click()
  const mobileCorrectionLayout = await page.evaluate(() => {
    const pane = document.querySelector('.round-correction-pane')
    const flow = pane?.querySelector('.round-correction-flow')
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      paneWidth: pane?.clientWidth ?? 0,
      paneScrollWidth: pane?.scrollWidth ?? 0,
      flowWidth: flow?.clientWidth ?? 0,
      flowScrollWidth: flow?.scrollWidth ?? 0,
      buttonVisible: Boolean(pane?.querySelector('.round-correction-submit')?.getBoundingClientRect().width),
    }
  })
  assert.ok(mobileCorrectionLayout.documentWidth <= mobileCorrectionLayout.viewportWidth + 1
    && mobileCorrectionLayout.paneScrollWidth <= mobileCorrectionLayout.paneWidth + 1
    && mobileCorrectionLayout.flowScrollWidth <= mobileCorrectionLayout.flowWidth + 1
    && mobileCorrectionLayout.buttonVisible,
  `mobile correction route stacks without horizontal overflow: ${JSON.stringify(mobileCorrectionLayout)}`)
  await page.screenshot({ path: path.join(evidence, 'route-correction-mobile.png'), fullPage: true, animations: 'disabled' })
  await routeSwitch.click()
  await page.setViewportSize({ width: 1393, height: 1000 })
  assert.ok((await nextChoice.locator('.next-round-review .el-select').innerText()).includes('不附带复习'))
  const reviewSelect = nextChoice.getByRole('combobox', { name: '副节点', exact:true })
  const reviewLayout = nextChoice.locator('.next-round-layout')
  const reviewLayoutHeightBefore = (await reviewLayout.boundingBox()).height
  await reviewSelect.focus()
  await page.keyboard.press('ArrowDown')
  const reviewDropdown = page.locator('.feedback-node-dropdown.el-popper:visible').last()
  await reviewDropdown.getByRole('option', { name: /证据复习节点.*复习清单\+分阶测试/ }).click()
  await reviewDropdown.waitFor({ state: 'hidden' })
  const reviewLayoutHeightAfter = (await reviewLayout.boundingBox()).height
  const reviewValue = await reviewSelect.evaluate(element => element.closest('.el-select').innerText)
  assert.ok(reviewValue.includes('复习清单+分阶测试') && Math.abs(reviewLayoutHeightBefore - reviewLayoutHeightAfter) <= 1,
    `review hint stays inside the selected field without resizing the plan: ${JSON.stringify({ reviewValue, reviewLayoutHeightBefore, reviewLayoutHeightAfter })}`)
  assert.equal(await nextChoice.locator('.next-round-review-hint').count(), 0,
    'selecting a review node must not add a separate hint row')
  await page.screenshot({ path: path.join(evidence, 'round-review-hint-inline.png'), fullPage: true, animations: 'disabled' })
  result.checks.push('Review-generation hint stays in parentheses inside the selector and selection does not change layout height')
  assert.ok(audit.requests.some(entry => entry.path === '/api/feedback/rounds/round-1/candidates'
    && new URLSearchParams(entry.query).get('source_attempt_id') === 'attempt-joint'))
  const submissions = audit.writes.filter(entry => entry.path.endsWith('/attempts'))
  assert.equal(submissions.length, 1); assert.equal(submissions[0].body.answers.length, 2)
  assert.equal(submissions[0].body.learning_reflection.comment, '轮次反思应完整提交')
  assert.ok(audit.requests.filter(entry => entry.path.endsWith('/result')).length >= 3)
  const claimPane = page.locator('.round-route-pane:not(.is-route-hidden)')
  const claimPillRadii = await claimPane.locator('.round-claim-switch').evaluateAll(items => items.map(item => getComputedStyle(item).borderRadius))
  assert.ok(claimPillRadii.length === 2 && claimPillRadii.every(radius => radius === '999px'),
    `Claim controls use rounded pill surfaces: ${JSON.stringify(claimPillRadii)}`)
  const claimSwitch = name => claimPane.locator('.round-claim-switch').filter({ hasText: name }).locator('.el-switch')
  const isOff = async name => claimSwitch(name).evaluate(element => element.classList.contains('is-disabled'))
  assert.equal(await isOff('缺证补检知识库'), true)
  await claimSwitch('Claim 强化审查').click()
  assert.equal(await isOff('缺证补检知识库'), false)
  await claimSwitch('缺证补检知识库').click()
  assert.equal(await page.locator('.claim-post-budget').count(), 0)
  await page.screenshot({ path: path.join(evidence, 'post-retrieval-options.png'), fullPage: true })
  await routeSwitch.press('Space')
  assert.equal(await routeSwitch.getAttribute('aria-checked'), 'true')
  await page.getByRole('button', { name: '生成选中节点的纠错包与新测试题' }).click()
  await page.waitForURL(/stageId=stage-1/)
  const correction = audit.writes.find(entry => entry.path.endsWith('/corrections'))
  assert.deepEqual(correction.body.targets, [{ node_id: 'n1', source_attempt_id: 'attempt-node-1' }, { node_id: 'n2', source_attempt_id: 'attempt-node-2' }])
  assert.equal(correction.body.include_claim_evidence_retrieval, true)
  assert.equal(correction.body.claim_post_retrieval_max_iterations, 0)
  assert.equal(detail().stages[1].members.reduce((n, member) => n + member.resource_types.length, 0), 4)
  await page.getByRole('button', { name: /附带复习.*证据复习节点/ }).click()
  await page.getByRole('region', { name: '学习资源预览' }).getByText('run-correction-2-body').waitFor()
  result.checks.push('Joint groups require all answers, one POST, independent scores, 202 result polling, two correction targets retain own source attempt and same round')
  result.checks.push('Both next-step routes share one grid row; switching keeps review and plan heights identical at 1393x1000, 1440x900 and 1280x800')
  legacy = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /历史节点.*检索主节点/ }).waitFor()
  assert.equal(await page.locator('.round-node-switch').count(), 1)
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
  const retakeStart = audit.writes.length
  const retakeButton = page.getByRole('button', { name: '再次测评', exact: true })
  assert.equal(await page.getByRole('button', { name: '查看结果', exact: true }).count(), 0)
  assert.ok(await retakeButton.evaluate(button => button.matches('.start-evaluation-button.el-button--primary') && Boolean(button.querySelector('svg'))))
  await retakeButton.click()
  const primaryAnswer = page.getByRole('textbox', { name: '检索主节点 第 1 题答案' })
  await primaryAnswer.waitFor()
  assert.equal(await primaryAnswer.inputValue(), '')
  await page.reload({ waitUntil: 'domcontentloaded' })
  await primaryAnswer.fill('再次作答')
  await page.getByRole('textbox', { name: '证据复习节点 第 1 题答案' }).fill('再次复习')
  await page.getByRole('button', { name: '统一提交本次测评' }).click()
  await page.getByRole('region', { name: '各节点独立测评结果' }).getByText('40 分').waitFor()
  const retakeWrites = audit.writes.slice(retakeStart)
  assert.equal(retakeWrites.filter(entry => entry.body?.retake_from_session_id === 'session-1').length, 1)
  const retakeSubmissions = retakeWrites.filter(entry => entry.path.endsWith('/attempts'))
  assert.equal(retakeSubmissions.length, 1)
  assert.equal(retakeSubmissions[0].body.session_id, 'session-2')
  assert.notEqual(retakeSubmissions[0].body.idempotency_key, recoverySubmissions[0].body.idempotency_key)
  await page.locator('.result-action-label').getByText('降阶补基础', { exact: true }).waitFor()
  await page.getByText('确认后切换到第 1 阶。', { exact: true }).waitFor()
  await page.getByRole('region', { name: '选择下一轮学习目标' }).getByText('基础前置 · 第 1 阶', { exact: true }).first().waitFor()
  result.checks.push('Retake reuses questions with empty answers, resumes after refresh and submits a new session once')
  assert.deepEqual(audit.errors, []); assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, [])
  result.status = 'PASS'
} catch (error) { result.status = 'FAIL'; result.error = error.stack; process.exitCode = 1; if (activePage) { await activePage.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }); writeFileSync(path.join(evidence, 'failure-body.txt'), await activePage.locator('body').innerText()) } }
finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify(result, null, 2)); console.log(`${result.status}: E14 built-app browser (${result.checks.length} scenarios)`); if (result.error) console.error(result.error) }
