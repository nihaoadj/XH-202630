import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(root, 'dist')
const evidence = path.resolve(process.env.TEST_RUN_OUTPUT || path.join(root, 'tests/test-results/resource-feedback-navigation'))
mkdirSync(evidence, { recursive: true })
const requests = [], errors = []
const jobs = ['old', 'new'].map((run, i) => ({ run_id: run, learner_id: 'learner', batch_id: 'batch',
  job_status: 'completed', created_at: `2026-11-14T0${i}:00:00Z`,
  request_payload: { resource_types: ['分阶测试题'], constraints: i ? { selection_type: 'correction_package' } : {} },
  round_binding: { round_id: 'round', stage_id: i ? 'correction' : 'initial', member_id: 'member' },
}))
const resources = jobs.map((job, i) => ({ id: `resource-${job.run_id}`, resource_id: `resource-${job.run_id}`,
  learner_id: 'learner', run_id: job.run_id, batch_id: 'batch', resource_type: '分阶测试题',
  resource_kind: 'learning_document', representation: 'text', publication_status: 'published',
  difficulty: '初级', knowledge_points: ['embedding'], created_at: job.created_at,
  content_text: `# ${i ? '纠错后新试题' : '初次学习旧试题'}`, source_refs: [],
}))
jobs.push({ ...jobs[0], run_id: 'archive', batch_id: 'archive-batch', created_at: '2026-11-13T00:00:00Z' })
resources.push({ ...resources[0], id: 'archive-resource', resource_id: 'archive-resource',
  run_id: 'archive', batch_id: 'archive-batch', created_at: '2026-11-13T00:00:00Z' })
const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://fixture')
  let file = path.join(dist, url.pathname)
  if (!file.startsWith(dist) || !existsSync(file) || !path.extname(file)) file = path.join(dist, 'index.html')
  const mime = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' }
  res.setHeader('content-type', mime[path.extname(file)] || 'application/octet-stream')
  res.end(readFileSync(file))
})
let browser, page
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  browser = await chromium.launch(browserOptions('RESOURCE_FEEDBACK_BROWSER_CHANNEL'))
  page = await browser.newPage({ viewport: { width: 1651, height: 871 } })
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', route => {
    const p = new URL(route.request().url()).pathname
    requests.push(p)
    let data = {}, status = 200
    if (p === '/api/auth/me') data = { user: { user_id: 'user', username: 'test' } }
    else if (p === '/api/profiles/') data = { items: [{ learner_id: 'learner', knowledge_base_id: 'kb', learner_type: '学习者', skill_level: '初级' }], total: 1 }
    else if (p === '/api/knowledge/domains') data = { domains: [{ tracks: [{ track_id: 'kb', name: '测试方向' }] }] }
    else if (p === '/api/skills/nodes') data = { nodes: [{ node_id: 'embedding', name: 'Embedding', tier: 1 }] }
    else if (p === '/api/generate/jobs') data = { items: jobs }
    else if (p === '/api/resource-library/learner') data = resources
    else if (p === '/api/resources/learner') data = { resources }
    else if (p.startsWith('/api/resources/items/')) {
      const resource = resources.find(r => r.resource_id === p.split('/')[4])
      data = { resource, content_text: resource?.content_text }
    } else if (p === '/api/feedback/results/learner') data = []
    else if (p === '/api/feedback/rounds/round') data = { round_id: 'round', learner_id: 'learner', members: [],
      stages: [{ stage_id: 'initial', kind: 'initial', ordinal: 0, members: [] }, { stage_id: 'correction', kind: 'correction', ordinal: 1, members: [] }] }
    else if (p.endsWith('/result')) { status = 404; data = { message: '隔离验证：仅确认请求对应阶段' } }
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
  })
  const base = `http://127.0.0.1:${server.address().port}`
  await page.addInitScript(() => localStorage.setItem('current_generation_run_id', 'archive'))
  await page.goto(`${base}/resources?learnerId=learner`)
  const batchSelector = page.locator('.toolbar-fields .field-label').nth(1).getByRole('combobox')
  await page.waitForFunction(() => document.querySelector('.toolbar-fields .field-label:nth-child(2)')?.textContent.includes('资源批次 02'))
  await batchSelector.click()
  const batchOptions = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
  assert.match(await batchOptions.nth(0).innerText(), /资源批次 02/)
  assert.match(await batchOptions.nth(1).innerText(), /资源批次 01/)
  await page.keyboard.press('Escape')
  await page.goto(`${base}/resources?learnerId=learner&resourceId=archive-resource`)
  await page.waitForFunction(() => document.querySelector('.toolbar-fields .field-label:nth-child(2)')?.textContent.includes('资源批次 01'))
  await page.goto(`${base}/resources?learnerId=learner&resourceId=resource-new`)
  await page.locator('.resource-shelf strong').getByText('分阶测试题 · 2', { exact: true }).waitFor()
  const shelf = page.locator('.resource-shelf')
  assert.match(await shelf.locator('.resource-item-copy').nth(1).getAttribute('title'), /纠错后复测 · 最新/)
  assert.doesNotMatch(await shelf.innerText(), /初次学习|纠错后复测|2026\/11/)
  assert.equal(await shelf.locator('.resource-item-copy small').count(), 2)
  await page.screenshot({ path: path.join(evidence, 'resource-stages.png') })
  await page.getByRole('button', { name: '反馈测评', exact: true }).click()
  await page.waitForURL(/\/feedback\?.*stageId=correction/)
  await page.waitForFunction(() => document.body.textContent.includes('隔离验证：仅确认请求对应阶段'))
  await page.getByRole('combobox', { name: '本轮资源批次', exact: true }).click()
  const feedbackBatches = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
  assert.match(await feedbackBatches.nth(0).innerText(), /资源批次 02/)
  assert.match(await feedbackBatches.nth(1).innerText(), /资源批次 01/)
  await page.keyboard.press('Escape')
  assert.ok(requests.some(p => p.includes('/stages/correction/result')))
  assert.equal(requests.some(p => p.includes('/stages/initial/result')), false)
  await page.goto(`${base}/resources?learnerId=learner&resourceId=resource-old&focus=1`)
  await page.locator('.focus-resource-switcher strong').getByText('分阶测试题 · 1', { exact: true }).waitFor()
  await page.getByRole('button', { name: '反馈测评', exact: true }).click()
  await page.waitForURL(/\/feedback\?.*stageId=initial/)
  assert.deepEqual(errors, [])
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify({ status: 'PASS', requests,
    checks: ['batch dropdown newest first, latest default ignores old cache, explicit archive link preserved', 'new resource requests correction result, never initial', 'old resource enters initial in focus mode', 'compact two-line cards; dot sequence markers; details in hover title'], errors }, null, 2))
} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
console.log('resource feedback navigation browser passed')
