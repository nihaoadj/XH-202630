import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = path.join(root, 'tests/test-results/courseware-sync')
mkdirSync(output, { recursive: true })
writeFileSync(path.join(output, 'harness.html'), '<html lang="zh-CN"><meta charset="utf-8"><body><div id="app"></div><script type="module" src="./harness.js"></script></body></html>')
writeFileSync(path.join(output, 'harness.js'), `
import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import CoursewareViewer from '/src/features/courseware/CoursewareViewer.vue'
import { useAuthStore } from '/src/stores/auth.js'
import { CoursewareEventQueue } from '/src/features/courseware/offlineEvents.js'
const pinia = createPinia()
const resource = ref({ resource_id: 'resource', released_release_id: 'release', title: '同步验收课件' })
const queue = new CoursewareEventQueue()
const auth = useAuthStore(pinia)
auth.setCurrentUser({ user_id: 'A', username: 'fixture' })
window.fixture = { queue, setUser: id => auth.setCurrentUser(id ? { user_id: id } : null),
  setRelease: id => { resource.value = { ...resource.value, released_release_id: id } },
  emit: event => document.querySelector('iframe').contentWindow.postMessage({ type: 'fixture-event', event }, '*'),
}
const app = createApp({ setup: () => () => h(CoursewareViewer, { resource: resource.value }) }).use(pinia)
window.fixture.unmount = () => app.unmount()
app.mount('#app')
`)
const server = await createServer({ root, configFile: false, plugins: [vue()], server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' })
await server.listen()
const origin = server.resolvedUrls.local[0].replace(/\/$/, '')
const harness = origin + '/tests/test-results/courseware-sync/harness.html'
const summary = { status: 'RUNNING', cases: [], requests: [], pageErrors: [], external: [] }
const browser = await chromium.launch(browserOptions('COURSEWARE_BROWSER_CHANNEL'))
const preview = `<body>课件 fixture<script>
window.addEventListener('message', event => {
 if (event.data.type === 'courseware-init') window.fixtureInit = event.data
 if (event.data.type === 'fixture-event' && window.fixtureInit) parent.postMessage({ type: 'learning_event', nonce: window.fixtureInit.nonce, resource_id: window.fixtureInit.resource_id, release_id: window.fixtureInit.release_id, event: event.data.event }, '*')
})</script>`
const contextFor = (account = 'A', releaseId = 'release') => ({ account, resourceId: 'resource', releaseId })
const eventFor = (id, release = 'release') => ({ event_id: id, occurrence_id: id, event_type: 'scene_viewed', resource_id: 'resource', release_id: release, scene_id: 'scene', state: { scene_index: 0 }, created_at: '2026-10-23T00:00:00Z', occurred_at: '2026-10-23T00:00:00Z' })
const contexts = []
async function setup(policy, { legacy, failStorage = false } = {}) {
 const context = await browser.newContext({ viewport: { width: 1100, height: 800 }, acceptDownloads: true })
 contexts.push(context)
 await context.addInitScript(({ legacy, failStorage }) => {
   if (window.parent !== window) return
   if (legacy) localStorage.setItem('zhiyu.courseware.learning-events.v1', JSON.stringify(legacy))
   const native = window.indexedDB
   window.failStorage = failStorage
   Object.defineProperty(window, 'indexedDB', { configurable: true, value: { open(...args) { if (window.failStorage) throw new Error('fixture storage failure'); return native.open(...args) } } })
 }, { legacy, failStorage })
 const requests = []
 await context.route('**/*', async route => {
   const url = new URL(route.request().url())
   if (url.origin !== origin) { summary.external.push(url.origin); return route.abort() }
   if (url.pathname === '/login') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<meta charset="utf-8"><button onclick="location.href='${harness}'">重新登录</button>` })
   if (!url.pathname.startsWith('/api/')) return route.continue()
   if (url.pathname.endsWith('/preview')) return route.fulfill({ contentType: 'text/html', body: preview })
   if (url.pathname.endsWith('/learning-progress')) return route.fulfill({ json: { current_scene_index: 0 } })
   if (url.pathname.endsWith('/learning-events')) {
     const events = route.request().postDataJSON().events
     assert.ok(events.length > 0 && events.length <= 100)
     assert.equal(new Set(events.map(event => event.release_id)).size, 1)
     const record = { events, resource: url.pathname, index: requests.length }
     requests.push(record); summary.requests.push({ size: events.length, release: events[0].release_id })
     if (policy) return policy(route, record)
     return route.fulfill({ json: { acknowledged_event_ids: events.map(event => event.event_id) } })
   }
   throw new Error('Unexpected API request: ' + url.pathname)
 })
 const page = await context.newPage()
 page.on('pageerror', error => summary.pageErrors.push(String(error)))
 await page.goto(harness)
 await page.waitForFunction(() => window.fixture && document.querySelector('iframe'))
 const child = page.frames().find(frame => frame.url().includes('/preview'))
 if (child) await child.waitForFunction(() => window.fixtureInit)
 return { context, page, requests }
}
async function seed(page, count, { account = 'A', release = 'release', prefix = 'event' } = {}) {
 await page.evaluate(async ({ count, account, release, prefix }) => {
   for (let i = 0; i < count; i++) await window.fixture.queue.enqueue(account, { event_id: `${prefix}-${i}`, occurrence_id: `${prefix}-${i}`, event_type: 'scene_viewed', resource_id: 'resource', release_id: release, scene_id: 'scene', state: { scene_index: i }, created_at: '2026-10-23T00:00:00Z', occurred_at: '2026-10-23T00:00:00Z' })
 }, { count, account, release, prefix })
}
const snapshot = (page, context = contextFor()) => page.evaluate(c => window.fixture.queue.snapshot(c), context)
async function waitEmpty(page, c = contextFor()) {
 const deadline = Date.now() + 10000
 while (Date.now() < deadline) {
  const state = await snapshot(page, c)
  const text = await page.getByRole('status').innerText()
  if (!state.error && state.pending.length === 0 && text.includes('已同步')) return
  await page.waitForTimeout(50)
 }
 throw new Error('queue did not settle: ' + JSON.stringify(await snapshot(page, c)))
}

try {
 {
  let failed = false
  const f = await setup(async (route, record) => {
   if (record.index === 1 && !failed) { failed = true; await f.context.setOffline(true); return route.abort('internetdisconnected') }
   return route.fulfill({ json: { acknowledged_event_ids: record.events.map(event => event.event_id) } })
  })
  await f.context.setOffline(true); await seed(f.page, 250); await f.context.setOffline(false)
  await f.page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('离线') || document.querySelector('[role=status]').textContent.includes('暂时'))
  assert.deepEqual(f.requests.map(item => item.events.length), [100, 100])
  assert.equal((await snapshot(f.page)).pending.length, 150)
  await f.context.setOffline(false); await f.page.evaluate(() => window.dispatchEvent(new Event('online'))); await waitEmpty(f.page)
  assert.deepEqual(f.requests.map(item => item.events.length), [100, 100, 100, 50])
  summary.cases.push('250 events, second batch network failure and online recovery')
  await f.context.close()
 }
 {
  const f = await setup((route, record) => route.fulfill({ json: { acknowledged_event_ids: record.index ? record.events.map(e => e.event_id) : [record.events[0].event_id, 'foreign'] } }))
  await f.context.setOffline(true); await seed(f.page, 5); await f.context.setOffline(false)
  await f.page.getByRole('status').filter({ hasText: '部分' }).waitFor()
  assert.equal((await snapshot(f.page)).pending.length, 4)
  await f.page.evaluate(event => window.fixture.emit(event), eventFor('during-send'))
  await waitEmpty(f.page)
  assert.ok(f.requests.slice(1).flatMap(item => item.events).some(event => event.event_id === 'during-send'))
  summary.cases.push('partial acknowledgement filters foreign IDs; new iframe event follows pending batch')
  await f.context.close()
 }
 {
  let releaseReply
  const gate = new Promise(resolve => { releaseReply = resolve })
  const f = await setup(async (route, record) => { if (!record.index) await gate; return route.fulfill({ json: { acknowledged_event_ids: [...record.events.map(e => e.event_id), 'B-new-0'] } }) })
  await seed(f.page, 1); await f.page.evaluate(() => window.dispatchEvent(new Event('online')))
  await f.page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('正在同步'))
  await seed(f.page, 1, { account: 'B', release: 'release-B', prefix: 'B-new' })
  await f.page.evaluate(() => { window.fixture.setUser('B'); window.fixture.setRelease('release-B') })
  releaseReply(); await waitEmpty(f.page, contextFor('B', 'release-B'))
  assert.ok(f.requests.some(item => item.events[0].event_id === 'B-new-0'))
  assert.equal((await snapshot(f.page)).pending.length, 0)
  summary.cases.push('late account/release response cannot acknowledge a different queue')
  await f.context.close()
 }
 for (const change of ['account-release', 'unmount']) {
  const f = await setup()
  await f.page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('学习进度将保存在本机'))
  await f.context.setOffline(true)
  await seed(f.page, 1, { prefix: 'held-A' })
  if (change === 'account-release') await seed(f.page, 1, { account: 'B', release: 'release-B', prefix: 'current-B' })
  await f.page.evaluate(async () => {
    const { CoursewareEventQueue } = await import('/src/features/courseware/offlineEvents.js')
    const snapshot = CoursewareEventQueue.prototype.snapshot
    let held = false
    CoursewareEventQueue.prototype.snapshot = async function (context) {
      const result = await snapshot.call(this, context)
      if (!held && this !== window.fixture.queue && context.account === 'A' && result.pending.some(item => item.event_id === 'held-A-0')) {
        held = true
        window.fixture.readHeld = true
        await new Promise(resolve => { window.fixture.releaseRead = resolve })
        window.fixture.readFinished = true
      }
      return result
    }
  })
  await f.context.setOffline(false)
  await f.page.evaluate(() => window.dispatchEvent(new Event('online')))
  await f.page.waitForFunction(() => window.fixture.readHeld)
  if (change === 'account-release') {
    await f.page.evaluate(() => { window.fixture.setUser('B'); window.fixture.setRelease('release-B') })
    await f.page.waitForFunction(() => document.querySelector('iframe').src.includes('release-B'))
  } else await f.page.evaluate(() => window.fixture.unmount())
  await f.page.evaluate(() => window.fixture.releaseRead())
  await f.page.waitForFunction(() => window.fixture.readFinished)
  if (change === 'account-release') await waitEmpty(f.page, contextFor('B', 'release-B'))
  else await f.page.waitForLoadState('networkidle')
  assert.deepEqual(f.requests.flatMap(item => item.events.map(event => event.event_id)), change === 'account-release' ? ['current-B-0'] : [])
  assert.deepEqual((await snapshot(f.page)).pending.map(event => event.event_id), ['held-A-0'])
  summary.cases.push(`pending IndexedDB read is cancelled before HTTP upload after ${change}`)
  await f.context.close()
 }
 {
  const f = await setup((route, record) => record.index === 0 ? route.fulfill({ status: 401, json: { detail: 'expired' } }) : route.fulfill({ json: { acknowledged_event_ids: record.events.map(e => e.event_id) } }))
  await seed(f.page, 1); await f.page.evaluate(() => window.dispatchEvent(new Event('online')))
  await f.page.waitForURL('**/login?redirect=*')
  await f.page.getByRole('button', { name: '重新登录' }).waitFor()
  await f.page.getByRole('button', { name: '重新登录' }).click(); await f.page.waitForFunction(() => window.fixture)
  await waitEmpty(f.page)
  assert.equal(f.requests.length, 2)
  assert.equal(f.requests[0].events[0].event_id, f.requests[1].events[0].event_id)
  summary.cases.push('actual Axios 401 redirect and relogin resume persisted event identity')
  await f.context.close()
 }
 for (const status of [409, 422]) {
  const f = await setup(route => route.fulfill({ status, json: { detail: 'fixture rejected' } }))
  await seed(f.page, 1); await f.page.evaluate(() => window.dispatchEvent(new Event('online')))
  await f.page.getByRole('button', { name: '导出待处理进度' }).waitFor()
  const before = f.requests.length
  await f.page.evaluate(() => window.dispatchEvent(new Event('online')))
  await f.page.waitForTimeout(100)
  assert.equal(f.requests.length, before)
  const download = f.page.waitForEvent('download')
  await f.page.getByRole('button', { name: '导出待处理进度' }).click()
  await (await download).saveAs(path.join(output, `blocked-${status}.json`))
  summary.cases.push(`HTTP ${status} quarantine remains exportable without automatic retries`)
  await f.context.close()
 }
 {
  const f = await setup(null, { legacy: [eventFor('legacy-unowned')] })
  await f.page.getByRole('button', { name: '导出待处理进度' }).waitFor()
  assert.equal((await snapshot(f.page)).unassigned, 1)
  assert.equal(f.requests.length, 0)
  await f.page.evaluate(() => window.fixture.setUser('B'))
  assert.equal((await snapshot(f.page, contextFor('B'))).unassigned, 1)
  summary.cases.push('v1 migration never assigns unknown events to either account')
  await f.context.close()
 }
 {
  const f = await setup(null, { failStorage: true })
  await f.page.evaluate(event => window.fixture.emit(event), eventFor('not-yet-saved'))
  await f.page.getByRole('button', { name: '重试保存' }).waitFor()
  await f.page.evaluate(() => { window.failStorage = false })
  await f.page.getByRole('button', { name: '重试保存' }).click(); await waitEmpty(f.page)
  assert.ok(f.requests.some(item => item.events[0].event_id === 'not-yet-saved'))
  summary.cases.push('storage failure is visible; retry persists before uploading')
  await f.context.close()
 }
 {
  const f = await setup()
  const second = await f.context.newPage()
  await second.goto(harness); await second.waitForFunction(() => window.fixture)
  await Promise.all([seed(f.page, 25, { prefix: 'tab-one' }), seed(second, 25, { prefix: 'tab-two' })])
  await Promise.all([f.page.evaluate(() => window.dispatchEvent(new Event('online'))), second.evaluate(() => window.dispatchEvent(new Event('online')))])
  await waitEmpty(f.page)
  const ids = f.requests.flatMap(item => item.events.map(event => event.event_id))
  assert.equal(new Set(ids).size, 50)
  assert.equal(ids.length, 50)
  await f.page.setViewportSize({ width: 375, height: 812 })
  await f.page.screenshot({ path: path.join(output, 'mobile-synced.png'), fullPage: true })
  assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  summary.cases.push('two tabs retain all events and Web Locks prevent overlapping duplicate upload')
  await f.context.close()
 }
 assert.deepEqual(summary.pageErrors, [])
 assert.deepEqual(summary.external, [])
 summary.status = 'PASS'
 console.log(`courseware sync browser PASS: ${summary.cases.length} scenarios`)
} catch (error) {
 summary.status = 'FAIL'; summary.error = String(error.stack)
 const active = contexts.at(-1)?.pages()[0]
 if (active) { summary.failureUrl = active.url(); await active.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {}) }
 throw error
} finally {
 writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2))
 for (const context of contexts) await context.close().catch(() => {})
 await browser.close(); await server.close()
}
