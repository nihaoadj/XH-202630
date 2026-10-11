import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'user-profile-ui')
const summaryPath = path.join(evidenceDir, 'summary.json')
if (!existsSync(path.join(distDir, 'index.html'))) throw new Error('先由主代理完成 build，再运行用户资料页浏览器验收；本脚本不会构建 dist')
mkdirSync(evidenceDir, { recursive: true })

const longIdentity = '临床研究协调与循证实践方向的跨学科学习者，持续负责多中心项目证据核验与质量管理工作。'.repeat(2).slice(0, 64)
const longEducation = '公共卫生与临床流行病学交叉培养项目硕士研究生，持续学习循证方法和数据治理。'.repeat(2).slice(0, 64)
const longMajor = '临床流行病学、真实世界研究设计、医疗数据治理与循证实践整合方向；重点覆盖来源追溯、字段映射、质量控制和研究报告复核。'.repeat(2).slice(0, 128)
const longJobRole = '负责多中心真实世界研究的方案协作、数据字典审阅、来源核验、跨团队交接与可复核证据归档；在临床、统计、信息和质量团队之间协调工作。'.repeat(2).slice(0, 128)
const filledUser = {
  user_id: 'fixture-user-42', username: 'profile.fixture', display_name: '用户资料验收账号',
  identity: longIdentity, education: longEducation, major: longMajor, job_role: longJobRole, experience_years: 12,
}
const shortUser = {
  user_id: 'fixture-user-42', username: 'profile.fixture', display_name: '用户资料验收账号',
  identity: '在读研究生', education: '硕士', major: '临床流行病学', job_role: '研究协调员', experience_years: 3,
}
const fallbackZeroUser = {
  user_id: 'fixture-user-42', username: 'profile.fixture', display_name: '用户资料验收账号',
  identity: '其他', education: '未填写', major: '未填写', job_role: null, experience_years: 0,
}
const fallbackNullUser = { ...fallbackZeroUser, experience_years: null }
const usersByScenario = { short: shortUser, filled: filledUser, fallbackZero: fallbackZeroUser, fallbackNull: fallbackNullUser }

const audit = { requests: [], writes: [], unexpectedApi: [], externalRequests: [], pageErrors: [], consoleErrors: [] }
const summary = {
  status: 'RUNNING', evidence_type: 'browser_fixture', mode: 'final', screenshots: [], checks: [], layouts: [],
  requestSummary: null, audit,
}
let activeScenario = 'filled'
let currentUser = structuredClone(filledUser)
let patchOutcome = 'success'
let patchDelayMs = 350
let expectedSaveErrorConsole = false
let browser
let context
let server
let baseUrl = ''
const pages = new Set()

function json(response, value, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(value))
}
function delay(ms) { return new Promise((resolve) => setTimeout(resolve, ms)) }
function recordRequest(request, url, body) {
  const entry = {
    method: (request.method || 'GET').toUpperCase(), path: url.pathname, query: url.search,
    body: body == null ? null : body, responseStatus: null,
  }
  audit.requests.push(entry)
  return entry
}
function userForScenario(name) { return structuredClone(usersByScenario[name] || filledUser) }
function allowedGet(pathname) {
  return pathname === '/api/auth/me'
    || pathname === '/api/knowledge/domains'
    || pathname === '/api/profiles/'
    || pathname === '/api/knowledge/directions'
    || pathname === '/api/skills/nodes'
    || /^\/api\/learning-history\/[^/]+\/journey$/.test(pathname)
}

server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://127.0.0.1')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    let rawBody = ''
    for await (const chunk of request) rawBody += chunk
    let body = null
    if (rawBody) {
      try { body = JSON.parse(rawBody) } catch { body = rawBody }
    }
    const entry = recordRequest(request, url, body)

    if (method === 'GET' && url.pathname === '/api/auth/me') {
      entry.responseStatus = 200
      return json(response, { user: structuredClone(currentUser) })
    }
    if (method === 'GET' && url.pathname === '/api/knowledge/domains') {
      entry.responseStatus = 200
      return json(response, { domains: [{ domain_id: 'domain-user-profile', tracks: [{ track_id: 'direction-user-profile', name: '用户资料验收方向' }] }] })
    }
    if (method === 'GET' && url.pathname === '/api/knowledge/directions') {
      entry.responseStatus = 200
      return json(response, { directions: [{ learning_direction_id: 'direction-user-profile', name: '用户资料验收方向' }] })
    }
    if (method === 'GET' && url.pathname === '/api/skills/nodes') {
      entry.responseStatus = 200
      return json(response, { nodes: [] })
    }
    if (method === 'GET' && url.pathname === '/api/profiles/') {
      entry.responseStatus = 200
      return json(response, { items: [], total: 0 })
    }
    const journeyMatch = url.pathname.match(/^\/api\/learning-history\/([^/]+)\/journey$/)
    if (method === 'GET' && journeyMatch) {
      entry.responseStatus = 200
      return json(response, {
        learner_id: decodeURIComponent(journeyMatch[1]), profile: null,
        current_state: { current_nodes: [], completed_nodes: [], next_action: null, latest_assessment: null },
        rounds: [], unlinked_events: [], total_rounds: 0, next_offset: null,
      })
    }
    if (method === 'PATCH' && url.pathname === '/api/users/fixture-user-42') {
      entry.allowed = true
      audit.writes.push(entry)
      await delay(patchDelayMs)
      if (patchOutcome === 'failure') {
        entry.responseStatus = 503
        return json(response, { message: '资料保存 fixture 故障，请重试。' }, 503)
      }
      currentUser = { ...currentUser, ...structuredClone(body), server_revision: (currentUser.server_revision || 0) + 1 }
      entry.responseStatus = 200
      return json(response, structuredClone(currentUser))
    }

    if (method !== 'GET') {
      entry.allowed = false
      audit.writes.push(entry)
    }
    if (method === 'GET' && allowedGet(url.pathname)) {
      entry.responseStatus = 200
      return json(response, {})
    }
    audit.unexpectedApi.push({ method, path: url.pathname, query: url.search })
    entry.responseStatus = 404
    return json(response, { message: 'Unexpected user profile UI fixture API request' }, 404)
  }

  const decodedPath = decodeURIComponent(url.pathname)
  const candidate = path.resolve(distDir, '.' + decodedPath)
  const prefix = distDir.endsWith(path.sep) ? distDir : distDir + path.sep
  const file = candidate.startsWith(prefix) && existsSync(candidate) && path.extname(candidate)
    ? candidate : path.join(distDir, 'index.html')
  const extension = path.extname(file).toLowerCase()
  const types = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ico': 'image/x-icon',
  }
  response.writeHead(200, { 'content-type': types[extension] || 'application/octet-stream', 'cache-control': 'no-cache' })
  response.end(readFileSync(file))
})

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
baseUrl = 'http://127.0.0.1:' + server.address().port
browser = await chromium.launch(browserOptions('USER_PROFILE_UI_BROWSER_CHANNEL'))
context = await browser.newContext()
context.setDefaultTimeout(8000)
context.setDefaultNavigationTimeout(15000)

async function newPage({ width, height, collapsed = false, reducedMotion = false } = {}) {
  const page = await context.newPage()
  await page.setViewportSize({ width, height })
  page.on('pageerror', (error) => audit.pageErrors.push({ message: error.message, url: page.url() }))
  page.on('console', (message) => {
    if (message.type() === 'error') audit.consoleErrors.push({ phase: expectedSaveErrorConsole ? 'expected-save-error' : 'unexpected', message: message.text().slice(0, 240) })
  })
  await page.route('**/*', async (route) => {
    const requestUrl = route.request().url()
    if (/^https?:/.test(requestUrl) && new URL(requestUrl).origin !== new URL(baseUrl).origin) {
      audit.externalRequests.push(requestUrl)
      return route.abort()
    }
    return route.continue()
  })
  await page.addInitScript((isCollapsed) => {
    localStorage.clear()
    localStorage.setItem('app_sidebar_collapsed', String(isCollapsed))
  }, collapsed)
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' })
  pages.add(page)
  return page
}

async function openProfile({ width = 1393, height = 871, collapsed = false, reducedMotion = false, scenario = 'filled' } = {}) {
  activeScenario = scenario
  currentUser = userForScenario(scenario)
  patchOutcome = 'success'
  const page = await newPage({ width, height, collapsed, reducedMotion })
  await page.goto(baseUrl + '/user/profile', { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '用户资料', level: 2 }).waitFor()
  await page.locator('.user-profile-page').waitFor()
  await page.locator('.profile-editor').waitFor()
  await inputOf(page, 'user-profile-username').waitFor()
  await page.evaluate(() => document.fonts.ready)
  return page
}

function inputOf(page, id) { return page.locator(`input#${id}, #${id} input`).first() }
async function fieldValue(page, id) { return inputOf(page, id).inputValue() }
async function setFields(page, values) {
  for (const [key, id] of Object.entries({
    identity: 'user-profile-identity', education: 'user-profile-education',
    major: 'user-profile-major', job_role: 'user-profile-job-role',
  })) await inputOf(page, id).fill(values[key] ?? '')
  await inputOf(page, 'user-profile-experience').fill(values.experience_years == null ? '' : String(values.experience_years))
}
async function readFields(page) {
  return {
    identity: await fieldValue(page, 'user-profile-identity'),
    education: await fieldValue(page, 'user-profile-education'),
    major: await fieldValue(page, 'user-profile-major'),
    job_role: await fieldValue(page, 'user-profile-job-role'),
    experience_years: await fieldValue(page, 'user-profile-experience'),
  }
}
async function waitFor(predicate, label, timeout = 7000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await predicate()) return
    await delay(40)
  }
  throw new Error('等待超时：' + label)
}
async function saveShot(page, filename) {
  const target = path.join(evidenceDir, filename)
  await page.screenshot({ path: target, animations: 'disabled' })
  summary.screenshots.push(path.relative(frontendDir, target).replaceAll('\\', '/'))
}
async function resetContentScroll(page) {
  await page.locator('.content-area').evaluate((element) => { element.scrollTop = 0 })
}
function overlaps(a, b) {
  return Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
    && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
}

function addCheck(name, status, details = {}) {
  summary.checks.push({ ...details, name, status })
  if (status !== 'PASS') summary.status = 'FAIL'
}
async function check(name, action) {
  try {
    const details = await action()
    addCheck(name, 'PASS', details || {})
  } catch (error) {
    addCheck(name, 'FAIL', { error: String(error?.stack || error).slice(0, 1400) })
  }
}
function assertNoOverlap(rects, labels) {
  for (let left = 0; left < rects.length; left += 1) {
    for (let right = left + 1; right < rects.length; right += 1) {
      if (overlaps(rects[left], rects[right])) throw new Error(`${labels[left]} 与 ${labels[right]} 重叠：${JSON.stringify({ left: rects[left], right: rects[right] })}`)
    }
  }
}
async function rgbContrast(page, selector, backgroundSelector) {
  return page.locator(selector).first().evaluate((element, backgroundQuery) => {
    const rgb = (value) => value.match(/[\d.]+/g).slice(0, 3).map(Number)
    const luminance = (channels) => {
      const linear = channels.map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    }
    const foreground = getComputedStyle(element).color
    let backgroundElement = document.querySelector(backgroundQuery)
    let background = backgroundElement ? getComputedStyle(backgroundElement).backgroundColor : getComputedStyle(element.parentElement).backgroundColor
    while (backgroundElement && /rgba\([^)]*,\s*0(?:\.0+)?\s*\)/.test(background) && backgroundElement.parentElement) {
      backgroundElement = backgroundElement.parentElement
      background = getComputedStyle(backgroundElement).backgroundColor
    }
    const a = luminance(rgb(foreground))
    const b = luminance(rgb(background))
    return { foreground, background, ratio: Number(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2)) }
  }, backgroundSelector)
}
async function assertVisualContract(page, label) {
  const metrics = await page.evaluate(() => {
    const rect = (element) => {
      const r = element.getBoundingClientRect()
      return { x: r.x, y: r.y, left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
    }
    const content = document.querySelector('.content-area')
    const save = document.querySelector('.profile-save-button')
    const saveRect = rect(save)
    const viewport = { width: window.innerWidth, height: window.innerHeight }
    const fixedControls = [
      ...document.querySelectorAll('.profile-direction-button, .profile-save-button'),
      ...document.querySelectorAll('.profile-editor .el-input__wrapper, .profile-editor .el-input-number'),
    ].map((element) => ({ tag: element.className, height: element.getBoundingClientRect().height }))
    const topbarRects = [...document.querySelectorAll('.topbar-copy, .topbar-actions, .topbar-meta')].map(rect)
    const major = ['.profile-page-intro', '.profile-workspace', '.account-panel', '.profile-editor'].map((selector) => ({ selector, rect: rect(document.querySelector(selector)) }))
    const inputRects = [...document.querySelectorAll('.profile-editor input')].filter((element) => element.getBoundingClientRect().width > 0).map((element) => ({ id: element.id || element.closest('[id]')?.id || '', rect: rect(element) }))
    return {
      viewport, document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, scrollHeight: document.documentElement.scrollHeight },
      content: { clientWidth: content.clientWidth, scrollWidth: content.scrollWidth, clientHeight: content.clientHeight, scrollHeight: content.scrollHeight, scrollTop: content.scrollTop },
      saveButton: { rect: saveRect, fullyInViewport: saveRect.top >= 0 && saveRect.bottom <= window.innerHeight && saveRect.left >= 0 && saveRect.right <= window.innerWidth },
      fixedControls, topbarRects, major, inputRects,
    }
  })
  assert.equal(metrics.document.scrollWidth, metrics.document.clientWidth, `${label}: document 有水平溢出 ${JSON.stringify(metrics.document)}`)
  assert.ok(metrics.content.scrollWidth <= metrics.content.clientWidth + 1, `${label}: content-area 有水平溢出 ${JSON.stringify(metrics.content)}`)
  for (const control of metrics.fixedControls) assert.ok(control.height >= 43.5, `${label}: 主控件高度小于 44px ${JSON.stringify(control)}`)
  assertNoOverlap(metrics.topbarRects, ['topbar-copy', 'topbar-actions', 'topbar-meta'])
  const mainRects = metrics.major.slice(0, 2).map((entry) => entry.rect)
  assertNoOverlap(mainRects, ['profile-page-intro', 'profile-workspace'])
  const [account, editor] = metrics.major.slice(2).map((entry) => entry.rect)
  assert.ok(account.right <= editor.left + 1 || editor.right <= account.left + 1 || account.bottom <= editor.top + 1 || editor.bottom <= account.top + 1, `${label}: 账号概览与编辑面板重叠`)
  for (const item of metrics.inputRects) assert.ok(item.rect.left >= 0 && item.rect.right <= metrics.viewport.width + 1, `${label}: 输入框越出视口 ${JSON.stringify(item)}`)
  const editorButton = page.locator('.profile-save-button')
  await editorButton.scrollIntoViewIfNeeded()
  const reachability = await editorButton.evaluate((element) => {
    const r = element.getBoundingClientRect()
    const content = document.querySelector('.content-area').getBoundingClientRect()
    return { rect: { top: r.top, bottom: r.bottom, left: r.left, right: r.right }, content: { top: content.top, bottom: content.bottom, left: content.left, right: content.right }, insideScrollContainer: r.top >= content.top - 1 && r.bottom <= content.bottom + 1 }
  })
  assert.ok(reachability.insideScrollContainer, `${label}: 保存按钮无法在页面滚动容器内自然到达 ${JSON.stringify(reachability)}`)
  metrics.reachability = reachability
  summary.layouts.push({ label, ...metrics })
  return metrics
}
async function verifyFieldContract(page) {
  const specs = [
    ['user-profile-username', '用户名', true, null],
    ['user-profile-identity', '身份', false, '64'],
    ['user-profile-education', '学历', false, '64'],
    ['user-profile-major', '专业', false, '128'],
    ['user-profile-job-role', '岗位 / 背景', false, '128'],
    ['user-profile-experience', '经验年限', false, null],
  ]
  const result = []
  for (const [id, label, disabled, maxLength] of specs) {
    const field = inputOf(page, id)
    await field.waitFor()
    assert.equal(await field.getAttribute('aria-label'), label, `${id} aria-label`)
    assert.equal(await field.isDisabled(), disabled, `${id} disabled`)
    if (maxLength) assert.equal(await field.getAttribute('maxlength'), maxLength, `${id} maxlength`)
    result.push({ id, label, disabled, maxLength, value: await field.inputValue() })
  }
  const experience = inputOf(page, 'user-profile-experience')
  assert.equal(await experience.getAttribute('min'), '0', 'experience min')
  assert.equal(await experience.getAttribute('max'), '50', 'experience max')
  assert.equal(await page.getByRole('heading', { name: '资料编辑', level: 3 }).count(), 1)
  assert.equal(await page.getByRole('heading', { name: /身份与教育/ }).count(), 1)
  assert.equal(await page.getByRole('heading', { name: /职业与经验/ }).count(), 1)
  assert.equal(await page.locator('.account-summary').count(), 1)
  return { fields: result, experienceMin: 0, experienceMax: 50 }
}
async function localStoredUser(page) {
  return page.evaluate(() => ({
    id: localStorage.getItem('current_user_id'),
    profile: JSON.parse(localStorage.getItem('current_user_profile') || 'null'),
  }))
}
function dtoFromValues(values) {
  return {
    identity: values.identity || '其他',
    education: values.education || '未填写',
    major: values.major || '未填写',
    job_role: values.job_role || null,
    experience_years: values.experience_years == null || values.experience_years === '' ? null : Number(values.experience_years),
  }
}
async function newestWrite(predicate = () => true) {
  return [...audit.writes].reverse().find(predicate) || null
}
async function waitForPatchCount(count) {
  await waitFor(async () => audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length >= count, `PATCH count ${count}`)
}
async function waitForPatchResponse(entry) {
  await waitFor(async () => entry.responseStatus != null, 'PATCH response')
}
async function captureLayout(page, label, filename) {
  await resetContentScroll(page)
  const metrics = await assertVisualContract(page, label)
  await resetContentScroll(page)
  await saveShot(page, filename)
  return metrics
}
async function directHistorySignature(page) {
  await page.mouse.move(0, 0)
  await delay(480)
  return page.evaluate(() => {
    const selectors = ['.topbar', '.topbar-copy', '.topbar-copy h1', '.topbar-copy p', '.topbar-kicker', '.topbar-actions', '.topbar-meta', '.content-area']
    const computed = (selector) => {
      const element = document.querySelector(selector)
      if (!element) return null
      const style = getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return {
        display: style.display, color: style.color, backgroundColor: style.backgroundColor, fontSize: style.fontSize,
        padding: style.padding, margin: style.margin, border: style.border, boxShadow: style.boxShadow,
        rect: [rect.x, rect.y, rect.width, rect.height].map((value) => Number(value.toFixed(2))),
      }
    }
    return Object.fromEntries(selectors.map((selector) => [selector, computed(selector)]))
  })
}

async function main() {
  const shortPage = await openProfile({ scenario: 'short' })
  await check('页面语义、字段 id/aria、maxlength、number 范围与用户名禁用', () => verifyFieldContract(shortPage))
  await check('常规短资料桌面首屏布局与保存可见性', async () => {
    const metrics = await assertVisualContract(shortPage, 'desktop-1393x871-short')
    await resetContentScroll(shortPage)
    await saveShot(shortPage, 'profile-desktop-short-first-viewport.png')
    assert.equal(metrics.saveButton.fullyInViewport, true, `1393×871 短资料下保存按钮应完整显示在首屏，实测 ${JSON.stringify(metrics.saveButton)}`)
    const result = { saveButton: metrics.saveButton, document: metrics.document, screenshot: 'tests/test-results/user-profile-ui/profile-desktop-short-first-viewport.png' }
    return result
  })

  await check('已保存资料概览与未提交表单状态隔离、长文案换行', async () => {
    const longPage = await openProfile({ scenario: 'filled' })
    await verifyFieldContract(longPage)
    const values = await readFields(longPage)
    assert.deepEqual(values, {
      identity: longIdentity, education: longEducation, major: longMajor, job_role: longJobRole, experience_years: '12',
    })
    const savedSummaryValues = await longPage.locator('.account-summary dd').allTextContents()
    assert.deepEqual(savedSummaryValues.slice(0, 2), [longIdentity, longEducation], '已保存概览中的长身份/学历应完整呈现')
    const summaryBefore = await longPage.locator('.account-summary').innerText()
    await inputOf(longPage, 'user-profile-identity').fill('尚未提交的身份修改')
    assert.equal(await longPage.locator('.account-summary').innerText(), summaryBefore, '编辑态不应提前改动仅来自 auth.currentUser 的已保存摘要')
    const geometry = await captureLayout(longPage, 'desktop-1393x871-long-copy', 'profile-desktop-long-copy.png')
    return { summaryUnchangedDuringEdit: true, longTextLengths: { identity: longIdentity.length, education: longEducation.length, major: longMajor.length, job_role: longJobRole.length }, document: geometry.document }
  })

  await check('有效保存：精确 PATCH、loading、直接 response 归一化与持久化', async () => {
    patchOutcome = 'success'
    patchDelayMs = 700
    await setFields(shortPage, { identity: '临床研究员', education: '博士', major: '流行病学', job_role: '项目负责人', experience_years: 0 })
    const expected = dtoFromValues(await readFields(shortPage))
    const beforeCount = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length
    const save = shortPage.locator('.profile-save-button')
    await save.click()
    await waitForPatchCount(beforeCount + 1)
    const write = await newestWrite((entry) => entry.path === '/api/users/fixture-user-42')
    await save.waitFor({ state: 'visible' })
    const loading = await save.evaluate((element) => ({ disabled: element.disabled, loading: element.classList.contains('is-loading'), height: element.getBoundingClientRect().height }))
    assert.ok(loading.disabled && loading.loading, `保存中按钮状态 ${JSON.stringify(loading)}`)
    assert.deepEqual(write.body, expected)
    await waitForPatchResponse(write)
    assert.equal(write.responseStatus, 200)
    const stored = await localStoredUser(shortPage)
    assert.equal(stored.id, 'fixture-user-42')
    assert.deepEqual(stored.profile, currentUser)
    assert.equal(await shortPage.locator('.account-summary').innerText(), ['身份\nIDENTITY\n临床研究员', '学历\nEDUCATION\n博士', '经验年限\nEXPERIENCE\n0年'].join('\n'))
    assert.deepEqual(await readFields(shortPage), { identity: expected.identity, education: expected.education, major: expected.major, job_role: expected.job_role, experience_years: '0' })
    assert.equal(await save.isDisabled(), false)
    return { method: write.method, path: write.path, payload: write.body, status: write.responseStatus, loading, localStorageKeys: { current_user_id: stored.id, current_user_profile: 'matches direct response' } }
  })

  await check('失败保存保留输入与已保存摘要、loading 恢复且可重试', async () => {
    const beforeStored = await localStoredUser(shortPage)
    const beforeSummary = await shortPage.locator('.account-summary').innerText()
    const draft = { identity: '失败后保留的身份', education: '继续教育', major: '医疗统计', job_role: '待重试岗位', experience_years: 8 }
    await setFields(shortPage, draft)
    patchOutcome = 'failure'
    patchDelayMs = 350
    expectedSaveErrorConsole = true
    const beforeCount = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length
    const save = shortPage.locator('.profile-save-button')
    await save.click()
    await waitForPatchCount(beforeCount + 1)
    const failure = await newestWrite((entry) => entry.path === '/api/users/fixture-user-42')
    await waitForPatchResponse(failure)
    assert.equal(failure.responseStatus, 503)
    assert.deepEqual(failure.body, dtoFromValues(draft))
    await shortPage.getByText('资料保存 fixture 故障，请重试。').waitFor({ state: 'visible' })
    await delay(200)
    expectedSaveErrorConsole = false
    assert.deepEqual(await readFields(shortPage), { ...draft, experience_years: '8' })
    assert.equal(await shortPage.locator('.account-summary').innerText(), beforeSummary)
    assert.deepEqual(await localStoredUser(shortPage), beforeStored)
    assert.equal(await save.isDisabled(), false)
    const failedButton = await save.evaluate((element) => ({ disabled: element.disabled, loading: element.classList.contains('is-loading') }))
    await saveShot(shortPage, 'profile-save-failure-retained-input.png')

    patchOutcome = 'success'
    patchDelayMs = 250
    const retryCount = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length
    await save.click()
    await waitForPatchCount(retryCount + 1)
    const retry = await newestWrite((entry) => entry.path === '/api/users/fixture-user-42')
    await waitForPatchResponse(retry)
    assert.equal(retry.responseStatus, 200)
    assert.deepEqual(retry.body, dtoFromValues(draft))
    assert.deepEqual((await localStoredUser(shortPage)).profile, currentUser)
    assert.equal(await shortPage.locator('.account-summary').getByText('失败后保留的身份').count(), 1)
    return { failedStatus: failure.responseStatus, retainedInputs: true, summaryUnchanged: true, localStorageUnchanged: true, buttonAfterFailure: failedButton, retryStatus: retry.responseStatus, retryPayload: retry.body }
  })

  await check('fallback sentinel、空字段、experience 0 保留与 PATCH fallback', async () => {
    const zeroPage = await openProfile({ scenario: 'fallbackZero' })
    await verifyFieldContract(zeroPage)
    const initial = await readFields(zeroPage)
    assert.deepEqual(initial, { identity: '', education: '', major: '', job_role: '', experience_years: '0' })
    const summaryText = await zeroPage.locator('.account-summary').innerText()
    assert.ok((summaryText.match(/待补充/g) || []).length >= 2)
    assert.ok(summaryText.includes('0年'))
    await saveShot(zeroPage, 'profile-fallback-empty-zero.png')
    const count = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length
    await zeroPage.locator('.profile-save-button').click()
    await waitForPatchCount(count + 1)
    const write = await newestWrite((entry) => entry.path === '/api/users/fixture-user-42')
    await waitForPatchResponse(write)
    assert.deepEqual(write.body, { identity: '其他', education: '未填写', major: '未填写', job_role: null, experience_years: 0 })
    assert.deepEqual((await localStoredUser(zeroPage)).profile, currentUser)
    return { initialForm: initial, savedPayload: write.body, summaryFallback: '待补充', zeroRendered: '0年', status: write.responseStatus }
  })

  await check('空值/null 年限不被转成 0，保留原 fallback 语义', async () => {
    const nullPage = await openProfile({ scenario: 'fallbackNull' })
    await verifyFieldContract(nullPage)
    assert.deepEqual(await readFields(nullPage), { identity: '', education: '', major: '', job_role: '', experience_years: '' })
    const count = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42').length
    await nullPage.locator('.profile-save-button').click()
    await waitForPatchCount(count + 1)
    const write = await newestWrite((entry) => entry.path === '/api/users/fixture-user-42')
    await waitForPatchResponse(write)
    assert.deepEqual(write.body, { identity: '其他', education: '未填写', major: '未填写', job_role: null, experience_years: null })
    assert.deepEqual((await localStoredUser(nullPage)).profile, currentUser)
    await saveShot(nullPage, 'profile-fallback-empty-null.png')
    return { initialForm: { experience_years: '' }, savedPayload: write.body, status: write.responseStatus }
  })

  await check('键盘 Tab 焦点可见且减少动态效果偏好生效', async () => {
    const motionPage = await openProfile({ width: 390, height: 844, reducedMotion: true, scenario: 'short' })
    const identity = inputOf(motionPage, 'user-profile-identity')
    await identity.focus()
    await motionPage.keyboard.press('Tab')
    const active = await motionPage.evaluate(() => {
      const wrapper = document.activeElement.closest('.el-input__wrapper')
      return {
        id: document.activeElement.id,
        label: document.activeElement.getAttribute('aria-label'),
        focusWrapper: Boolean(wrapper?.classList.contains('is-focus')),
        focusBoxShadow: wrapper ? getComputedStyle(wrapper).boxShadow : '',
      }
    })
    assert.equal(active.label, '学历', `Tab 应进入学历输入框，当前 ${JSON.stringify(active)}`)
    assert.ok(active.focusWrapper && /2px/.test(active.focusBoxShadow), `键盘焦点环缺失 ${JSON.stringify(active)}`)
    const durations = await motionPage.locator('.profile-save-button, .profile-direction-button, .profile-editor .el-input__wrapper').evaluateAll((elements) => elements.map((element) => ({ selector: element.className, duration: getComputedStyle(element).transitionDuration })))
    for (const item of durations) assert.ok(item.duration.split(',').every((part) => Number.parseFloat(part) <= 0.001), `reduced-motion duration ${JSON.stringify(item)}`)
    await saveShot(motionPage, 'profile-mobile-reduced-motion-focus.png')
    return { tabFocus: active, reducedMotionDurations: durations }
  })

  await check('浅色与深色区域文字、保存按钮对比度达到 4.5:1', async () => {
    const pairs = [
      ['.profile-page-intro p', '.content-area'],
      ['.profile-field-label', '.profile-editor'],
      ['.account-summary dd', '.account-panel'],
      ['.account-summary dt', '.account-panel'],
      ['.profile-save-button', '.profile-save-button'],
    ]
    const ratios = []
    for (const [textSelector, backgroundSelector] of pairs) {
      const contrast = await rgbContrast(shortPage, textSelector, backgroundSelector)
      ratios.push({ textSelector, backgroundSelector, ...contrast })
      assert.ok(contrast.ratio >= 4.5, `对比度不足 ${JSON.stringify(ratios.at(-1))}`)
    }
    return { ratios }
  })

  const viewports = [
    { name: 'desktop-expanded-1393x871', width: 1393, height: 871, collapsed: false, screenshot: 'profile-desktop-1393x871.png' },
    { name: 'desktop-collapsed-1331x871', width: 1331, height: 871, collapsed: true, screenshot: 'profile-desktop-collapsed-1331x871.png' },
    { name: 'large-1920x1080', width: 1920, height: 1080, collapsed: false, screenshot: 'profile-large-1920x1080.png' },
    { name: 'short-height-1393x620', width: 1393, height: 620, collapsed: false, screenshot: 'profile-short-height-1393x620.png' },
    { name: 'mobile-390x844', width: 390, height: 844, collapsed: false, screenshot: 'profile-mobile-390x844.png' },
    { name: 'mobile-375x667', width: 375, height: 667, collapsed: false, screenshot: 'profile-mobile-375x667.png' },
  ]
  for (const viewport of viewports) {
    await check(`响应式布局 ${viewport.name} 无横溢出、重叠且保存可达`, async () => {
      const page = await openProfile({ ...viewport, scenario: 'short' })
      await verifyFieldContract(page)
      const geometry = await captureLayout(page, viewport.name, viewport.screenshot)
      if (viewport.name === 'desktop-expanded-1393x871') assert.ok(geometry.saveButton.fullyInViewport, `1393×871 保存按钮应完整显示在首屏，实测 ${JSON.stringify(geometry.saveButton)}`)
      return { width: viewport.width, height: viewport.height, collapsed: viewport.collapsed, saveButtonFirstViewportVisible: geometry.saveButton.fullyInViewport, contentScrollHeight: geometry.content.scrollHeight }
    })
  }

  await check('新建方向入口导航及历史页主题隔离与直达一致', async () => {
    const navPage = await openProfile({ scenario: 'short' })
    await navPage.getByRole('button', { name: '去新建学习方向' }).click()
    await navPage.waitForURL('**/learning/new')
    await navPage.locator('.onboarding-page').waitFor()
    const knowledgeRequest = audit.requests.find((entry) => entry.method === 'GET' && entry.path === '/api/knowledge/domains')
    assert.ok(knowledgeRequest, 'learning/new 未获取 fixture domains')

    const routedPage = await openProfile({ scenario: 'short' })
    await routedPage.getByRole('button', { name: /学习历史/ }).click()
    await routedPage.waitForURL('**/learning/history')
    await routedPage.locator('.history-page').waitFor()
    await routedPage.getByRole('heading', { name: '学习画像', level: 2 }).waitFor()
    const routedSignature = await directHistorySignature(routedPage)
    assert.equal(await routedPage.locator('.app-shell:has(.user-profile-page)').count(), 0, '离开页面后 history 路由仍被资料页隔离选择器匹配')

    const directPage = await newPage({ width: 1393, height: 871, collapsed: false })
    await directPage.goto(baseUrl + '/learning/history', { waitUntil: 'domcontentloaded' })
    await directPage.locator('.history-page').waitFor()
    await directPage.getByRole('heading', { name: '学习画像', level: 2 }).waitFor()
    const directSignature = await directHistorySignature(directPage)
    assert.deepEqual(routedSignature, directSignature, '经由资料页历史入口后的页面样式与直接访问不一致')
    await saveShot(routedPage, 'profile-route-history-style-isolation.png')
    return { newDirectionRoute: navPage.url(), knowledgeRequest, profileIsolationMatchesAfterRoute: false, routedHistoryStyleMatchesDirect: true, directHistorySignature: directSignature }
  })

  await check('浏览器请求隔离、fixture 唯一写入与页面错误审计', async () => {
    assert.deepEqual(audit.unexpectedApi, [])
    assert.deepEqual(audit.externalRequests, [])
    assert.deepEqual(audit.pageErrors, [])
    const expectedConsole = audit.consoleErrors.filter((entry) => entry.phase === 'expected-save-error')
    const unexpectedConsole = audit.consoleErrors.filter((entry) => entry.phase !== 'expected-save-error')
    assert.equal(unexpectedConsole.length, 0, `意外 console.error ${JSON.stringify(unexpectedConsole)}`)
    assert.equal(expectedConsole.filter((entry) => /AxiosError: Request failed with status code 503/i.test(entry.message)).length, 1, `应只记录一次预期的 Axios 503 console.error ${JSON.stringify(expectedConsole)}`)
    assert.equal(expectedConsole.filter((entry) => /server responded with a status of 503/i.test(entry.message)).length, 1, `应只记录一次对应的浏览器资源 503 日志 ${JSON.stringify(expectedConsole)}`)
    const nonFixtureWrites = audit.writes.filter((entry) => !(entry.method === 'PATCH' && entry.path === '/api/users/fixture-user-42'))
    assert.deepEqual(nonFixtureWrites, [])
    const fixturePatches = audit.writes.filter((entry) => entry.path === '/api/users/fixture-user-42')
    assert.ok(fixturePatches.length >= 5)
    return { requestCount: audit.requests.length, fixturePatchCount: fixturePatches.length, unexpectedApi: 0, externalRequests: 0, pageErrors: 0, expectedSaveConsoleErrors: expectedConsole.length, nonFixtureWrites: 0 }
  })
}

try {
  await main()
} catch (error) {
  summary.status = 'FAIL'
  summary.fatalError = String(error?.stack || error).slice(0, 1600)
} finally {
  patchOutcome = 'success'
  expectedSaveErrorConsole = false
  try { await Promise.all([...pages].map((page) => page.close())) } catch {}
  try { await context?.close() } catch {}
  try { await browser?.close() } catch {}
  try { server?.close() } catch {}

  summary.requestSummary = {
    total: audit.requests.length,
    byMethodPathStatus: audit.requests.reduce((result, entry) => {
      const key = `${entry.method} ${entry.path} ${entry.responseStatus ?? 'pending'}`
      result[key] = (result[key] || 0) + 1
      return result
    }, {}),
    writes: audit.writes.map(({ method, path: requestPath, body, responseStatus }) => ({ method, path: requestPath, body, responseStatus })),
  }
  if (summary.status !== 'FAIL') summary.status = 'PASS'
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + '\n')
  process.stdout.write(JSON.stringify({ status: summary.status, checks: summary.checks.map(({ name, status }) => ({ name, status })), layouts: summary.layouts.map(({ label, viewport, saveButton }) => ({ label, viewport, saveButton })), screenshots: summary.screenshots, requestSummary: summary.requestSummary, fatalError: summary.fatalError || null, summary: summaryPath }, null, 2) + '\n')
  if (summary.status !== 'PASS') process.exitCode = 1
}
