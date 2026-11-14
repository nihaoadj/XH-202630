// Built GenerateView with isolated HTTP/SSE fixtures; no user backend/model.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, readFileSync, statSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = path.join(frontend, 'tests/test-results/courseware-task-navigation')
const server = createServer((req, res) => {
  const requested = path.resolve(dist, '.' + new URL(req.url, 'http://localhost').pathname)
  const file = requested.startsWith(dist + path.sep) && existsSync(requested) && statSync(requested).isFile()
    ? requested : path.join(dist, 'index.html')
  res.setHeader('content-type', ({ '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[path.extname(file)] || 'text/html')
  res.end(readFileSync(file))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`
const learner = 'navigation-learner'
const binding = { round_id: 'round-nav', member_id: 'member-nav', stage_id: 'stage-nav', stage_node_id: 'scope-nav', role: 'primary' }
const text = { run_id: 'run-text', learner_id: learner, job_status: 'completed', batch_id: 'batch-text', topic: 'Chunk 切分',
  created_at: '2026-11-14T10:00:00Z', round_binding: binding,
  request_payload: { target_skill_nodes: ['chunking'], resource_types: ['实操指南'] } }
const courseware = (id, node, title, resourceType) => ({ run_id: id, learner_id: learner, status: 'queued', source_batch_id: 'batch-text',
  created_at: '2026-11-14T11:00:00Z', updated_at: '2026-11-14T11:00:00Z', scenes: [], warnings: [],
  request_options: { learning_goal: id + ' 的独立课件工作区' },
  source_summary: [{ resource_id: 'source-' + id, resource_type: resourceType, title, topic: node === 'chunking' ? 'Chunk 切分' : 'Embedding', knowledge_points: [node], version: 1 }] })
const alpha = courseware('cw_alpha1234', 'chunking', '固定长度与段落切分实操指南', '实操指南')
const beta = courseware('cw_beta1234', 'embedding', 'Embedding 边界与检索质量复习清单', '复习清单')
const jobs = [alpha, beta]
const member = { member_id: 'member-nav', node_id: 'chunking', node_name: 'Chunk 切分', role: 'primary', state: 'awaiting_assessment' }
const round = { round_id: 'round-nav', learner_id: learner, protocol_version: 'learning-round/v1', members: [member],
  stages: [{ stage_id: 'stage-nav', kind: 'initial', ordinal: 0, members: [{ ...member, stage_node_id: 'scope-nav', job_ids: ['run-text'], resource_ids: [], resource_types: ['实操指南'] }] }] }
const audit = { errors: [], writes: [], unexpected: [], textCoursewareRequests: [], detailRequests: [], roundCalls: 0, listCalls: 0 }
let releaseRound, releaseList
const roundGate = new Promise(resolve => { releaseRound = resolve })
const listGate = new Promise(resolve => { releaseList = resolve })
const browser = await chromium.launch(browserOptions('COURSEWARE_NAVIGATION_BROWSER_CHANNEL'))
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
page.on('pageerror', error => audit.errors.push(error.message))
await page.route('**/*', async route => {
  const req = route.request(); const url = new URL(req.url()); const p = url.pathname
  if (url.origin !== origin) { audit.unexpected.push(url.origin); return route.abort() }
  if (!p.startsWith('/api/')) return route.continue()
  if (req.method() !== 'GET') { audit.writes.push(p); return route.fulfill({ status: 405, json: {} }) }
  let body
  if (p === '/api/auth/me') body = { user: { user_id: 'nav-user', username: 'nav-user', display_name: '导航验收' } }
  else if (p === '/api/profiles/') body = { items: [{ learner_id: learner, user_id: 'nav-user', learner_type: '导航验收', knowledge_base_id: 'kb', skill_level: '初级' }] }
  else if (p === '/api/knowledge/domains') body = { domains: [{ tracks: [{ track_id: 'kb', knowledge_base_id: 'kb', name: 'RAG 工程' }] }] }
  else if (p === '/api/skills/nodes') body = { nodes: [{ node_id: 'chunking', name: 'Chunk 切分', tier: 2 }, { node_id: 'embedding', name: 'Embedding', tier: 1 }] }
  else if (p === '/api/generate/capabilities') body = { round_creation_enabled: true }
  else if (p === '/api/generate/jobs') body = { items: [text] }
  else if (p === '/api/generate/jobs/run-text') body = text
  else if (p === '/api/resources/courseware/jobs') {
    audit.listCalls++
    if (audit.listCalls === 2) { await listGate; body = { items: [alpha] } }
    else body = { items: jobs }
  } else if (p.match(/^\/api\/resources\/courseware\/jobs\/cw_/)) {
    const id = p.split('/')[5]; const job = jobs.find(item => item.run_id === id)
    if (p.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: ': fixture\n\n' })
    audit.detailRequests.push(id)
    body = job
  } else if (p === '/api/feedback/rounds/round-nav') { audit.roundCalls++; await roundGate; body = round }
  else if (p === `/api/resources/${learner}`) body = { resources: [], total: 0 }
  else if (p === `/api/resource-library/${learner}`) body = []
  else if (p.startsWith('/api/runs/')) {
    const id = p.split('/')[3]
    if (id.startsWith('cw_')) audit.textCoursewareRequests.push(p)
    if (p.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: 'event: snapshot\ndata: {"run_id":"run-text","is_terminal":true,"run_status":"completed","last_event_sequence":0}\n\n' })
    body = p.endsWith('/timeline') ? { run: { run_id: id, status: 'completed' }, steps: [], events: [] } : { run_id: id, items: [] }
  } else if (p.startsWith('/api/feedback/results/')) body = []
  else { audit.unexpected.push(p); body = {} }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body ?? {}) })
})

async function until(predicate, label) {
  const end = Date.now() + 10000
  while (!predicate()) {
    assert.ok(Date.now() < end, label)
    await new Promise(resolve => setTimeout(resolve, 20))
  }
}
async function pick(id) {
  await page.getByRole('combobox', { name: '资源批次' }).press('ArrowDown')
  await page.locator(`.generation-batch-dropdown:visible [data-run-id="${id}"]`).click()
  await page.waitForURL(url => url.pathname === '/generate' && url.searchParams.get('runId') === id)
}
async function visibleBeta() {
  await page.waitForFunction(() => document.querySelector('.courseware-generation-page')?.textContent.includes('cw_beta1234 的独立课件工作区'))
}
const checks = []
try {
  await page.goto(`${origin}/generate?learnerId=${learner}&runId=run-text&roundId=round-nav&memberId=member-nav&stageId=stage-nav`)
  await until(() => audit.roundCalls > 0, 'initial round detail requested')
  await pick(alpha.run_id)
  await until(() => audit.listCalls >= 2, 'embedded courseware list requested')
  releaseRound()
  await pick(beta.run_id)
  await visibleBeta()
  releaseList()
  await until(() => audit.detailRequests.filter(id => id === beta.run_id).length >= 2, 'delayed list retains parent selected run')
  await visibleBeta()
  assert.equal(new URL(page.url()).searchParams.get('runId'), beta.run_id)
  for (const key of ['roundId', 'memberId', 'stageId']) assert.equal(new URL(page.url()).searchParams.has(key), false)
  checks.push('old round and stale courseware list do not override the selected HTML run')
  await page.getByRole('combobox', { name: '资源批次' }).press('ArrowDown')
  const item = page.locator(`.generation-batch-dropdown:visible [data-run-id="${beta.run_id}"]`)
  assert.match(await item.innerText(), /Embedding 边界与检索质量复习清单/)
  assert.match(await item.innerText(), /第 1 阶/)
  mkdirSync(evidence, { recursive: true })
  await page.waitForTimeout(350) // Finish the selector's opening transition before visual evidence.
  await page.screenshot({ path: path.join(evidence, 'source-labelled-picker.png') })
  await page.keyboard.press('Escape')
  assert.match(await page.locator('.batch-selected').innerText(), /原资源：Embedding 边界与检索质量复习清单/)
  checks.push('picker and selected label show node, original source name and tier')
  const roundCalls = audit.roundCalls
  await page.goto(`${origin}/generate?learnerId=${learner}&runId=${beta.run_id}&roundId=round-nav&memberId=member-nav&stageId=stage-nav`)
  await visibleBeta()
  assert.equal(audit.roundCalls, roundCalls, 'courseware deep link must not restore a text round')
  await pick('run-text')
  await page.locator('.studio-grid').waitFor()
  assert.equal(new URL(page.url()).searchParams.get('roundId'), 'round-nav')
  assert.equal(await page.locator('.courseware-generation-page').count(), 0)
  await pick(beta.run_id)
  await visibleBeta()
  checks.push('reload with stale round query and return from text preserve exact courseware selection')
  beta.status = 'published'; beta.resource_id = 'html-beta'
  await page.getByRole('group', { name: '课件任务操作', exact: true }).getByRole('button', { name: '刷新状态', exact: true }).click()
  await page.getByRole('button', { name: '进入学习', exact: true }).waitFor()
  await page.waitForFunction(() => document.querySelector('.job-summary .production-status')?.textContent.includes('已发布'))
  assert.equal(new URL(page.url()).pathname, '/generate')
  assert.equal(new URL(page.url()).searchParams.get('runId'), beta.run_id)
  checks.push('publication refresh updates state without navigating away')
  assert.deepEqual(audit.textCoursewareRequests, [])
  assert.deepEqual(audit.errors, [])
  assert.deepEqual(audit.writes, [])
  assert.deepEqual(audit.unexpected, [])
  await page.getByRole('button', { name: '进入学习', exact: true }).click()
  await page.waitForURL(url => url.pathname === '/resources' && url.searchParams.get('resourceId') === 'html-beta')
  assert.equal(new URL(page.url()).searchParams.get('runId'), 'batch-text')
  checks.push('only explicit enter-learning action opens the exact published resource')
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify({ status: 'PASS', checks, audit }, null, 2))
  console.log('PASS courseware task navigation: ' + checks.length + ' checks')
} finally {
  releaseRound(); releaseList()
  await browser.close()
  await new Promise(resolve => server.close(resolve))
}
