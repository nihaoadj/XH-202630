import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'tutor-ui')
const screenshotsDir = path.join(evidenceDir, 'screenshots')
const fixtureIdentity = {
  learnerId: 'learner-tutor-fixture-2026',
  knowledgeBaseId: 'kb-tutor-fixture-2026',
  runId: 'run-tutor-fixture-2026',
  batchId: 'batch-tutor-fixture-2026',
  resourceId: 'resource-tutor-fixture-2026',
  questionId: 'question-tutor-fixture-2026',
}
const quoteText = '冻结来源：每次提交后记录操作者、提交时间与结果状态。'
const fixtureUser = {
  user_id: 'user-tutor-fixture-2026',
  username: 'tutor.fixture',
  display_name: 'Tutor 浏览器验收用户',
}
const fixtureProfile = {
  learner_id: fixtureIdentity.learnerId,
  knowledge_base_id: fixtureIdentity.knowledgeBaseId,
  skill_level: '中级',
  learner_type: '个人学习者',
  profile_version: 3,
  learning_goal: '核对材料中的发布审计步骤',
  created_at: '2026-10-01T08:00:00Z',
  learning_preferences: { metadata: { user_profile_snapshot: { display_name: 'Tutor 浏览器验收用户' } } },
}
const sourceRefs = [{
  evidence_id: 'evidence-tutor-fixture-1',
  document_id: 'doc-tutor-protocol',
  chunk_id: 'chunk-protocol-07',
  title: '发布审计操作规范',
  section: '2.4 提交记录',
  page: 5,
  normalized_score: 0.93,
}]
const fixtureResource = {
  id: fixtureIdentity.resourceId,
  resource_id: fixtureIdentity.resourceId,
  learner_id: fixtureIdentity.learnerId,
  run_id: fixtureIdentity.runId,
  batch_id: fixtureIdentity.batchId,
  resource_type: '讲义',
  resource_kind: 'learning_document',
  topic: '发布审计与证据核验',
  title: '发布审计操作规范',
  difficulty: '中级',
  knowledge_points: ['提交记录', '冻结来源'],
  content_text: `# 发布审计操作规范\n\n${quoteText}\n\n收到请求后，先核对请求范围，再写入操作记录。\n\n记录应保留可供复核的来源位置。`,
  source_refs: sourceRefs,
  created_at: '2026-10-01T08:06:00Z',
  published_at: '2026-10-01T08:06:00Z',
  publication_status: 'published',
  file_path: '/fixture/resources/resource-tutor-fixture-2026.md',
  version: 1,
}
const apiAudit = { requests: [], writes: [], unexpectedApi: [], externalRequests: [], pageErrors: [] }
const summary = {
  status: 'RUNNING',
  evidence_type: 'browser_fixture',
  screenshots: [],
  layout: [],
  checks: [],
  audit: apiAudit,
}
const logLines = []
const sessions = new Map()
const failOnceByTurn = new Set()
const topbarStyleViolations = []
const layoutViolations = []
let turnSequence = 0
let browser
let serverStarted = false
let baseUrl = ''

if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before Tutor browser verification')
}
mkdirSync(screenshotsDir, { recursive: true })

function log(message) {
  const line = `${new Date().toISOString()} ${message}`
  logLines.push(line)
  process.stdout.write(`${line}\n`)
}

function writeJson(response, value, status = 200) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json; charset=utf-8')
  response.end(JSON.stringify(value))
}

async function readJson(request) {
  let rawBody = ''
  for await (const chunk of request) rawBody += chunk
  if (!rawBody) return null
  try { return JSON.parse(rawBody) } catch { return rawBody }
}

function sessionFor(sessionId) {
  return sessions.get(sessionId)
}

function makeTurn(session, requestBody) {
  turnSequence += 1
  const message = String(requestBody?.message || '')
  const insufficient = message.includes('EVIDENCE_INSUFFICIENT')
  const isLong = message.length >= 3500
  return {
    turn_id: `turn-tutor-fixture-${turnSequence}`,
    session_id: session.session_id,
    client_message_id: requestBody?.client_message_id,
    user_message: message,
    pedagogy_action: insufficient ? 'evidence_insufficient' : 'explanation',
    hint_level: insufficient ? 1 : 2,
    message: insufficient
      ? '当前材料没有提供足够依据来确认这个结论。我会先说明证据边界。'
      : isLong
        ? '针对这段较长的问题，先核对操作对象，再逐项检查执行结果。\n' + '长回复用于验证窄视口中的换行与滚动。'.repeat(90)
        : '先对照冻结来源确认记录字段，再核对提交结果是否可复查。',
    follow_up_question: insufficient ? null : '你能指出这一步对应材料中的哪一条记录吗？',
    grounding_status: insufficient ? 'evidence_insufficient' : 'grounded',
    source_refs: insufficient ? [] : sourceRefs,
    created_at: '2026-10-12T02:00:00Z',
  }
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://tutor-fixture')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    const body = method === 'GET' ? null : await readJson(request)
    const record = { method, path: url.pathname, query: url.search, body }
    apiAudit.requests.push(record)

    if (method === 'GET' && url.pathname === '/api/auth/me') return writeJson(response, { user: fixtureUser })
    if (method === 'GET' && url.pathname === '/api/profiles/') return writeJson(response, { items: [fixtureProfile], total: 1 })
    if (method === 'GET' && url.pathname === `/api/profiles/${fixtureIdentity.learnerId}`) return writeJson(response, { profile: fixtureProfile })
    if (method === 'GET' && url.pathname === `/api/profiles/${fixtureIdentity.learnerId}/ability-nodes`) return writeJson(response, { nodes: [] })
    if (method === 'GET' && url.pathname === '/api/knowledge/domains') {
      return writeJson(response, { domains: [{ domain_id: 'domain-tutor-fixture', tracks: [{ track_id: fixtureIdentity.knowledgeBaseId, name: 'RAG 工程' }] }] })
    }
    if (method === 'GET' && url.pathname === '/api/knowledge/directions') return writeJson(response, { directions: [] })
    if (method === 'GET' && url.pathname === '/api/knowledge/info') return writeJson(response, { knowledge_base_id: fixtureIdentity.knowledgeBaseId, name: 'RAG 工程' })
    if (method === 'GET' && url.pathname === '/api/skills/nodes') return writeJson(response, { nodes: [] })
    if (method === 'GET' && url.pathname === '/api/onboarding/questions') return writeJson(response, { questions: [] })
    if (method === 'GET' && url.pathname === `/api/resources/${fixtureIdentity.learnerId}`) {
      return writeJson(response, { resources: [fixtureResource] })
    }
    if (method === 'GET' && url.pathname === `/api/resource-library/${fixtureIdentity.learnerId}`) {
      return writeJson(response, [{ ...fixtureResource, id: fixtureIdentity.resourceId }])
    }
    if (method === 'GET' && url.pathname === `/api/resources/items/${fixtureIdentity.resourceId}`) {
      return writeJson(response, { resource: fixtureResource })
    }
    if (method === 'GET' && url.pathname === '/api/generate/jobs') return writeJson(response, { items: [], total: 0 })
    if (method === 'GET' && url.pathname === '/api/resources/courseware/jobs') return writeJson(response, { items: [], total: 0 })
    if (method === 'GET' && url.pathname === `/api/feedback/results/${fixtureIdentity.learnerId}`) return writeJson(response, [])
    if (method === 'GET' && url.pathname === `/api/feedback/evaluation/batch/${fixtureIdentity.learnerId}/${fixtureIdentity.batchId}`) {
      return writeJson(response, {
        learner_id: fixtureIdentity.learnerId,
        batch_id: fixtureIdentity.batchId,
        topic: '发布审计与证据核验',
        resource_ids: [fixtureIdentity.resourceId],
        total: 1,
        questions: [{
          question_id: fixtureIdentity.questionId,
          question_type: 'short_answer',
          question: '提交操作后应记录哪些信息？',
          options: [],
          skill_node_id: 'node-audit-records',
          knowledge_point: '提交记录',
          difficulty: '中级',
          source: 'resource',
        }],
      })
    }

    const sessionMatch = url.pathname.match(/^\/api\/tutor\/sessions\/([^/]+)$/)
    const turnMatch = url.pathname.match(/^\/api\/tutor\/sessions\/([^/]+)\/turns$/)
    const closeMatch = url.pathname.match(/^\/api\/tutor\/sessions\/([^/]+)\/close$/)
    const isTutorWrite = method === 'POST' && (
      url.pathname === '/api/tutor/sessions' || Boolean(turnMatch) || Boolean(closeMatch)
    )
    if (method !== 'GET') apiAudit.writes.push({ ...record, allowed: isTutorWrite })
    if (method === 'POST' && url.pathname === '/api/tutor/sessions') {
      const sessionId = body?.context_type === 'question_help' ? 'session-tutor-question-fixture' : 'session-tutor-resource-fixture'
      const session = {
        session_id: sessionId,
        learner_id: fixtureIdentity.learnerId,
        source_type: body?.source_type,
        resource_id: body?.resource_id || null,
        batch_id: body?.batch_id || null,
        run_id: body?.run_id || null,
        context_type: body?.context_type,
        question_id: body?.question_id || null,
        status: 'active',
      }
      sessions.set(sessionId, { session, turns: [] })
      return writeJson(response, session, 201)
    }
    if (method === 'GET' && sessionMatch) {
      const found = sessionFor(decodeURIComponent(sessionMatch[1]))
      if (!found) return writeJson(response, { detail: 'Tutor session not found' }, 404)
      return writeJson(response, { session: found.session, turns: found.turns })
    }
    if (method === 'POST' && turnMatch) {
      const found = sessionFor(decodeURIComponent(turnMatch[1]))
      if (!found) return writeJson(response, { detail: 'Tutor session not found' }, 404)
      const clientId = String(body?.client_message_id || '')
      const failKey = `${found.session.session_id}:${String(body?.message || '')}`
      if (String(body?.message || '').includes('FAIL_ONCE') && !failOnceByTurn.has(failKey)) {
        failOnceByTurn.add(failKey)
        return writeJson(response, { message: 'fixture Tutor unavailable' }, 503)
      }
      await new Promise(resolve => setTimeout(resolve, 420))
      const turn = makeTurn(found.session, body)
      found.turns.push(turn)
      return writeJson(response, turn)
    }
    if (method === 'POST' && closeMatch) {
      const found = sessionFor(decodeURIComponent(closeMatch[1]))
      if (!found) return writeJson(response, { detail: 'Tutor session not found' }, 404)
      found.session.status = 'closed'
      return writeJson(response, found.session)
    }

    apiAudit.unexpectedApi.push({ method, path: url.pathname, query: url.search })
    return writeJson(response, { detail: 'Unexpected fixture API request' }, 404)
  }

  const decodedPath = decodeURIComponent(url.pathname)
  const candidatePath = path.resolve(distDir, `.${decodedPath}`)
  const safePrefix = distDir.endsWith(path.sep) ? distDir : distDir + path.sep
  let filePath = candidatePath.startsWith(safePrefix) || candidatePath === path.join(distDir, 'index.html')
    ? candidatePath
    : path.join(distDir, 'index.html')
  if (!existsSync(filePath) || !readFileSync(filePath).length) filePath = path.join(distDir, 'index.html')
  const extension = path.extname(filePath).toLowerCase()
  const contentTypes = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2', '.ico': 'image/x-icon',
  }
  response.setHeader('content-type', contentTypes[extension] || 'application/octet-stream')
  response.end(readFileSync(filePath))
})

function attachPageAudit(page) {
  page.setDefaultTimeout(8000)
  page.on('pageerror', error => apiAudit.pageErrors.push({ message: error.message, url: page.url() }))
  page.on('request', request => {
    const requestUrl = request.url()
    if (/^https?:/.test(requestUrl) && new URL(requestUrl).origin !== new URL(baseUrl).origin) {
      apiAudit.externalRequests.push({ url: requestUrl, method: request.method() })
    }
  })
}

async function openPage(route, viewport = { width: 1301, height: 871 }, { reducedMotion = false } = {}) {
  const page = await browser.newPage({ viewport })
  attachPageAudit(page)
  await page.addInitScript((identity) => {
    localStorage.clear()
    localStorage.setItem('last_learner_id', identity.learnerId)
    localStorage.setItem('current_generation_run_id', identity.batchId)
    localStorage.setItem('learning_direction_id', identity.knowledgeBaseId)
    localStorage.setItem('learning_direction_name', 'RAG 工程')
    localStorage.setItem('current_profile', JSON.stringify({
      learner_id: identity.learnerId,
      knowledge_base_id: identity.knowledgeBaseId,
      skill_level: '中级',
      profile_version: 3,
    }))
    localStorage.setItem('app_sidebar_collapsed', 'true')
  }, fixtureIdentity)
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded' })
  return page
}

function resourceRoute({ focus = false } = {}) {
  const query = new URLSearchParams({
    learnerId: fixtureIdentity.learnerId,
    runId: fixtureIdentity.batchId,
    resourceId: fixtureIdentity.resourceId,
  })
  if (focus) query.set('focus', '1')
  return `/resources?${query}`
}

async function saveScreenshot(page, name) {
  const target = path.join(screenshotsDir, name)
  await page.screenshot({ path: target, fullPage: false, animations: 'disabled' })
  summary.screenshots.push(path.relative(evidenceDir, target).replaceAll('\\', '/'))
  log(`screenshot ${name}`)
}

async function saveComposerScreenshot(page, name) {
  const composer = page.locator('.tutor-composer')
  await composer.waitFor({ state: 'visible' })
  await page.evaluate(() => document.fonts?.ready)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const target = path.join(screenshotsDir, name)
  await composer.screenshot({ path: target, animations: 'disabled' })
  summary.screenshots.push(path.relative(evidenceDir, target).replaceAll('\\', '/'))
  log(`composer screenshot ${name}`)
}

async function waitForResource(page) {
  await page.locator('.resource-content').getByText(quoteText, { exact: true }).waitFor()
  await page.getByRole('button', { name: '向 Tutor 提问' }).waitFor()
}

async function createResourceTutor(page, { quote = false } = {}) {
  if (quote) {
    await page.evaluate(text => {
      const paragraph = [...document.querySelectorAll('.resource-content p')].find(node => node.textContent.includes(text))
      const node = paragraph?.firstChild
      const start = node?.textContent.indexOf(text) ?? -1
      if (!node || start < 0) throw new Error('Fixture quote was not present in the rendered resource')
      const range = document.createRange()
      range.setStart(node, start)
      range.setEnd(node, start + text.length)
      const selection = window.getSelection()
      selection.removeAllRanges()
      selection.addRange(range)
      paragraph.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }, quoteText)
    await page.getByRole('button', { name: '就这段向 Tutor 提问' }).waitFor()
    await page.getByRole('button', { name: '就这段向 Tutor 提问' }).click()
  } else {
    await page.getByRole('button', { name: '向 Tutor 提问' }).evaluate(button => {
      button.click()
      button.click()
    })
  }
  await page.locator('.tutor-panel').waitFor({ state: 'visible' })
  await page.locator('.tutor-panel textarea').waitFor()
  await page.waitForFunction(() => {
    const textarea = document.querySelector('.tutor-panel textarea')
    return textarea && !textarea.disabled
  })
  await page.waitForFunction(() => {
    const panel = document.querySelector('.tutor-panel')
    const rect = panel?.getBoundingClientRect()
    return rect && rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1
  }, null, { timeout: 1400 }).catch(() => {})
}

async function checkSessionScope(page, contextType, questionId = null) {
  const creates = apiAudit.writes.filter(item => item.path === '/api/tutor/sessions')
  const last = creates.at(-1)
  assert.ok(last, 'Tutor session creation should be audited')
  assert.deepEqual(last.body, {
    learner_id: fixtureIdentity.learnerId,
    source_type: contextType === 'question_help' ? 'batch' : 'resource',
    resource_id: contextType === 'resource_help' ? fixtureIdentity.resourceId : null,
    run_id: null,
    batch_id: contextType === 'question_help' ? fixtureIdentity.batchId : null,
    context_type: contextType,
    question_id: questionId,
  })
  const sessionId = last.path === '/api/tutor/sessions'
    ? creates.length === 1 || contextType === 'resource_help'
      ? 'session-tutor-resource-fixture'
      : 'session-tutor-question-fixture'
    : ''
  assert.ok(sessionId)
  summary.checks.push({ name: `session-scope-${contextType}`, payload: last.body, page: page.url() })
  return sessionId
}

function rgbChannels(value) {
  const match = value.match(/[\d.]+/g)?.map(Number)
  return match?.length >= 3 ? match.slice(0, 3) : null
}

function contrastRatio(foreground, background) {
  const luminance = color => {
    const channels = rgbChannels(color)
    if (!channels) return null
    const [r, g, b] = channels.map(channel => channel / 255).map(channel => (
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
    ))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const first = luminance(foreground)
  const second = luminance(background)
  if (first === null || second === null) return null
  const [lighter, darker] = [first, second].sort((a, b) => b - a)
  return (lighter + 0.05) / (darker + 0.05)
}

async function inspectTutor(page, label, { mobile = false } = {}) {
  const geometry = await page.evaluate(() => {
    const panel = document.querySelector('.tutor-panel')
    const header = panel?.querySelector('.tutor-panel-header')
    const body = panel?.querySelector('.tutor-body')
    const footer = panel?.querySelector('.tutor-composer')
    const textarea = panel?.querySelector('textarea')
    const send = panel?.querySelector('.composer-send')
    const userBubble = panel?.querySelector('.user-bubble')
    const bounds = element => {
      const rect = element?.getBoundingClientRect()
      return rect ? { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height } : null
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      panel: bounds(panel), header: bounds(header), body: bounds(body), footer: bounds(footer),
      textarea: bounds(textarea), send: bounds(send), userBubble: bounds(userBubble),
      panelClientWidth: panel?.clientWidth,
      panelScrollWidth: panel?.scrollWidth,
      bodyClientWidth: body?.clientWidth,
      bodyBorderLeft: body ? parseFloat(getComputedStyle(body).borderLeftWidth) : 0,
      tutorBodyScrollHeight: body?.scrollHeight,
      tutorBodyClientHeight: body?.clientHeight,
      tutorBodyScrollTop: body?.scrollTop,
      bodyOverflowY: body ? getComputedStyle(body).overflowY : '',
      bodyPaddingRight: body ? parseFloat(getComputedStyle(body).paddingRight) : 0,
      sendColor: send ? getComputedStyle(send).color : '',
      sendBackground: send ? getComputedStyle(send).backgroundColor : '',
      textColor: textarea ? getComputedStyle(textarea).color : '',
      textBackground: (() => {
        let node = textarea
        while (node) {
          const color = getComputedStyle(node).backgroundColor
          if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') return color
          node = node.parentElement
        }
        return 'rgb(255, 255, 255)'
      })(),
      headingColor: panel?.querySelector('.tutor-heading > strong') ? getComputedStyle(panel.querySelector('.tutor-heading > strong')).color : '',
      bodyTextColor: panel?.querySelector('.assistant-bubble > p') ? getComputedStyle(panel.querySelector('.assistant-bubble > p')).color : '',
      pageTextColor: panel?.querySelector('.composer-label') ? getComputedStyle(panel.querySelector('.composer-label')).color : '',
    }
  })
  assert.ok(geometry.panel, `${label}: Tutor panel should be mounted`)
  const recordLayoutIssue = (condition, message) => {
    if (!condition) layoutViolations.push({ label, message })
  }
  recordLayoutIssue(geometry.panel.x >= -1 && geometry.panel.right <= geometry.viewport.width + 1, 'panel should fit viewport')
  recordLayoutIssue(geometry.header.y >= -1 && geometry.header.bottom <= geometry.viewport.height + 1, 'header should be visible')
  recordLayoutIssue(geometry.footer.y >= 0 && geometry.footer.bottom <= geometry.viewport.height + 1, 'composer should remain in viewport')
  recordLayoutIssue(geometry.body.bottom <= geometry.footer.y + 1, 'message body should end above the composer')
  recordLayoutIssue(geometry.bodyOverflowY === 'auto', 'conversation body should be scrollable')
  recordLayoutIssue(geometry.panelScrollWidth <= geometry.panelClientWidth + 1, 'panel should not scroll horizontally')
  recordLayoutIssue(geometry.documentWidth <= geometry.viewport.width + 1 && geometry.bodyWidth <= geometry.viewport.width + 1,
    'page should not overflow horizontally')
  recordLayoutIssue(geometry.textarea.x >= geometry.panel.x - 1 && geometry.textarea.right <= geometry.panel.right + 1,
    'composer textarea should be reachable')
  recordLayoutIssue(Math.round(geometry.send.width) === (mobile ? 44 : 36), 'send target width should match touch/desktop size')
  recordLayoutIssue(mobile ? geometry.send.height >= 44 : Math.round(geometry.send.height) === 36,
    mobile ? 'mobile send target should be at least 44px high' : 'desktop send target should be about 36px high')
  const rightContentEdge = geometry.body.x + geometry.bodyBorderLeft + geometry.bodyClientWidth - geometry.bodyPaddingRight
  const userBubbleRightDelta = geometry.userBubble ? Math.abs(rightContentEdge - geometry.userBubble.right) : null
  if (geometry.userBubble) recordLayoutIssue(userBubbleRightDelta <= 2, 'user message should align to the conversation right edge')
  const contrasts = {
    input: contrastRatio(geometry.textColor, geometry.textBackground),
    heading: contrastRatio(geometry.headingColor, 'rgb(255, 255, 255)'),
    assistant: contrastRatio(geometry.bodyTextColor, 'rgb(255, 255, 255)'),
    composerLabel: contrastRatio(geometry.pageTextColor, 'rgb(255, 255, 255)'),
    send: contrastRatio(geometry.sendColor, geometry.sendBackground),
  }
  for (const [part, ratio] of Object.entries(contrasts)) {
    if (ratio !== null) {
      const minimum = part === 'send' ? 3 : 4.5
      recordLayoutIssue(ratio >= minimum, `${part} contrast is ${ratio.toFixed(2)}:1, expected at least ${minimum}:1`)
    }
  }
  const check = { name: `tutor-layout-${label}`, mobile, geometry, userBubbleRightDelta, contrasts }
  summary.layout.push(check)
  log(`layout ${label} ${JSON.stringify({ viewport: geometry.viewport, panel: geometry.panel, footer: geometry.footer, send: geometry.send, contrasts })}`)
  return check
}

async function inspectTopbarColors(page, routeName) {
  await page.locator('.app-shell').waitFor()
  await page.waitForFunction(() => {
    const buttons = [...document.querySelectorAll('.topbar-actions .topbar-action')]
    return buttons.length === 3 && buttons.every(button => {
      const text = button.querySelector('.el-button__text') || button.lastElementChild || button
      return getComputedStyle(button).color === 'rgb(23, 44, 69)'
        && getComputedStyle(button).fontWeight === '600'
        && getComputedStyle(text).color === 'rgb(23, 44, 69)'
        && getComputedStyle(text).fontWeight === '600'
    })
  }, null, { timeout: 1400 }).catch(() => {})
  const actions = await page.locator('.topbar-actions .topbar-action').evaluateAll(buttons => buttons.map(button => ({
    label: button.innerText.trim().replace(/\s+/g, ' '),
    className: button.className,
    color: getComputedStyle(button).color,
    weight: getComputedStyle(button).fontWeight,
    textColor: getComputedStyle(button.querySelector('.el-button__text') || button.lastElementChild || button).color,
    textWeight: getComputedStyle(button.querySelector('.el-button__text') || button.lastElementChild || button).fontWeight,
    dashboardInk: getComputedStyle(document.querySelector('.app-shell')).getPropertyValue('--dashboard-ink').trim(),
    shellClass: document.querySelector('.app-shell').className,
  })))
  summary.checks.push({ name: `topbar-style-observed-${routeName}`, actions })
  if (actions.length !== 3) topbarStyleViolations.push({ routeName, message: `expected 3 actions, received ${actions.length}`, actions })
  for (const action of actions) {
    if (action.color !== 'rgb(23, 44, 69)' || action.textColor !== 'rgb(23, 44, 69)'
      || action.weight !== '600' || action.textWeight !== '600') {
      topbarStyleViolations.push({ routeName, action })
    }
  }
  summary.checks.push({ name: `topbar-style-${routeName}`, passed: actions.length === 3 && actions.every(action => (
    action.color === 'rgb(23, 44, 69)' && action.textColor === 'rgb(23, 44, 69)' && action.weight === '600' && action.textWeight === '600'
  )), actions })
  log(`topbar ${routeName} ${JSON.stringify(actions)}`)
  await page.close()
}

async function checkTopbarRoutes() {
  const routes = [
    ['dashboard', '/dashboard'],
    ['onboarding', '/learning/new'],
    ['generate', '/generate'],
    ['resources', resourceRoute()],
    ['feedback', `/feedback?learnerId=${fixtureIdentity.learnerId}&batchId=${fixtureIdentity.batchId}`],
  ]
  for (const [name, route] of routes) {
    const page = await openPage(route)
    await inspectTopbarColors(page, name)
  }
}

async function checkResourceConversation() {
  const page = await openPage(resourceRoute(), { width: 1301, height: 871 })
  try {
    await waitForResource(page)
    await createResourceTutor(page, { quote: true })
    const sessionId = await checkSessionScope(page, 'resource_help')
    const textarea = page.locator('.tutor-panel textarea')
    assert.equal(await page.locator('.tutor-welcome').count(), 1, 'new Tutor session should show an empty welcome state')
    await page.getByText('已引用材料', { exact: true }).waitFor()
    await saveScreenshot(page, 'resource-empty-1301x871.png')
    await inspectTutor(page, 'resource-empty-1301x871')

    await textarea.fill('请说明这一步。')
    await textarea.press('Shift+Enter')
    await textarea.type('并给出依据。')
    const multiline = await textarea.inputValue()
    assert.equal(multiline, '请说明这一步。\n并给出依据。', 'Shift+Enter should insert a newline')
    const firstRequestPromise = page.waitForRequest(request => request.url().includes(`/api/tutor/sessions/${sessionId}/turns`))
    await textarea.press('Enter')
    await page.locator('.thinking-bubble').waitFor({ state: 'visible' })
    await firstRequestPromise
    assert.equal(await textarea.isDisabled(), true, 'composer should be disabled while a reply is pending')
    const firstTurnCount = apiAudit.writes.filter(item => item.path.endsWith('/turns')).length
    await page.locator('.composer-send').evaluate(button => button.click())
    assert.equal(apiAudit.writes.filter(item => item.path.endsWith('/turns')).length, firstTurnCount,
      'a second send during an active request should be ignored')
    const firstTurn = apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1)
    assert.equal(firstTurn.path, `/api/tutor/sessions/${sessionId}/turns`)
    assert.ok(firstTurn.body.message.includes(`引用材料：\n“${quoteText}”`), 'request should include the selected quoted text')
    assert.ok(firstTurn.body.message.endsWith('我的问题：\n请说明这一步。\n并给出依据。'), 'request should include the user question and Shift+Enter newline')
    assert.ok(firstTurn.body.client_message_id, 'turn request should carry an idempotency client message id')
    await page.getByText('你能指出这一步对应材料中的哪一条记录吗？', { exact: true }).waitFor()
    await page.locator('.tutor-panel').getByText('发布审计操作规范', { exact: true }).waitFor()
    await page.locator('.tutor-panel').getByText('第 5 页', { exact: false }).waitFor()
    assert.ok(await page.locator('.user-bubble p').innerText().then(text => text.includes(quoteText)))
    await saveScreenshot(page, 'resource-grounded-reply-1301x871.png')
    await inspectTutor(page, 'resource-grounded-reply-1301x871')

    await textarea.fill('EVIDENCE_INSUFFICIENT')
    await page.getByRole('button', { name: '发送' }).click()
    await page.getByText('本轮未调用自由知识回答', { exact: true }).waitFor()
    assert.ok(apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1).body.message.includes('EVIDENCE_INSUFFICIENT'))
    await saveScreenshot(page, 'resource-evidence-insufficient-1301x871.png')

    await textarea.fill('FAIL_ONCE 请解释失败后如何重试')
    await page.getByRole('button', { name: '发送' }).click()
    await page.getByText('fixture Tutor unavailable', { exact: true }).waitFor()
    assert.equal(await textarea.inputValue(), 'FAIL_ONCE 请解释失败后如何重试', 'failed turn should restore the unsent user input')
    const failedClientId = apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1).body.client_message_id
    await page.getByRole('button', { name: '发送' }).click()
    await page.getByText('先对照冻结来源确认记录字段，再核对提交结果是否可复查。', { exact: true }).last().waitFor()
    const retriedTurn = apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1)
    assert.notEqual(retriedTurn.body.client_message_id, failedClientId, 'retry should have its own client message id')

    await page.getByRole('button', { name: '关闭 Tutor' }).click()
    await page.locator('.tutor-panel').waitFor({ state: 'hidden' })
    const getBeforeRestore = apiAudit.requests.filter(item => item.method === 'GET' && item.path === `/api/tutor/sessions/${sessionId}`).length
    const createsBeforeRestore = apiAudit.writes.filter(item => item.path === '/api/tutor/sessions').length
    await page.getByRole('button', { name: '向 Tutor 提问' }).click()
    await page.locator('.tutor-panel').waitFor({ state: 'visible' })
    await page.getByText('EVIDENCE_INSUFFICIENT', { exact: true }).waitFor()
    const getAfterRestore = apiAudit.requests.filter(item => item.method === 'GET' && item.path === `/api/tutor/sessions/${sessionId}`).length
    assert.equal(getAfterRestore, getBeforeRestore + 1, 'reopening should restore the existing Tutor session with GET')
    assert.equal(apiAudit.writes.filter(item => item.path === '/api/tutor/sessions').length, createsBeforeRestore,
      'reopening should not create a duplicate Tutor session')
    summary.checks.push({ name: 'resource-session-restore', sessionId, getAfterRestore, createsBeforeRestore })

    await textarea.fill('x'.repeat(4000))
    assert.equal(await textarea.getAttribute('maxlength'), '4000')
    await textarea.press('End')
    await textarea.type('x')
    assert.equal((await textarea.inputValue()).length, 4000, 'composer should enforce its 4000 character limit')
    await page.getByRole('button', { name: '发送' }).click()
    await page.getByText('针对这段较长的问题，先核对操作对象', { exact: false }).waitFor()
    const longTurn = apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1)
    assert.equal(longTurn.body.message.length, 4000, 'the full 4000 character message should be sent')
    await page.evaluate(() => {
      const body = document.querySelector('.tutor-body')
      body.scrollTop = body.scrollHeight
    })
    const scrollMetrics = await page.locator('.tutor-body').evaluate(body => ({ scrollHeight: body.scrollHeight, clientHeight: body.clientHeight, scrollTop: body.scrollTop }))
    assert.ok(scrollMetrics.scrollHeight > scrollMetrics.clientHeight, 'long conversation content should exceed the body viewport')
    assert.ok(scrollMetrics.scrollTop > 0, 'long conversation should scroll inside the message body')
    summary.checks.push({ name: 'long-message-and-conversation-scroll', sentLength: longTurn.body.message.length, scrollMetrics })
    await saveScreenshot(page, 'resource-long-conversation-1301x871.png')
    await inspectTutor(page, 'resource-long-conversation-1301x871')
  } finally {
    await page.close()
  }
}

async function checkQuestionTutorEntry() {
  const page = await openPage(`/feedback?learnerId=${fixtureIdentity.learnerId}&batchId=${fixtureIdentity.batchId}`)
  try {
    await page.locator('.feedback-page').waitFor()
    await page.getByRole('button', { name: '开始测评' }).click()
    await page.getByText('提交操作后应记录哪些信息？', { exact: true }).waitFor()
    await page.getByRole('button', { name: '需要提示' }).click()
    await page.locator('.tutor-panel').waitFor({ state: 'visible' })
    await page.waitForFunction(() => {
      const textarea = document.querySelector('.tutor-panel textarea')
      return textarea && !textarea.disabled
    })
    const sessionId = await checkSessionScope(page, 'question_help', fixtureIdentity.questionId)
    assert.equal(await page.locator('.quoted-context').count(), 0, 'question Tutor entry should not invent quoted resource text')
    const textarea = page.locator('.tutor-panel textarea')
    await saveComposerScreenshot(page, 'feedback-question-composer-empty.png')
    await textarea.fill('请先给我一个方向')
    await textarea.focus()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    await page.waitForFunction(() => {
      const field = document.querySelector('.tutor-panel textarea')
      return document.activeElement === field && field.matches(':focus-visible')
    })
    await saveComposerScreenshot(page, 'feedback-question-composer-focused.png')
    const turnRequestPromise = page.waitForRequest(request => request.url().includes(`/api/tutor/sessions/${sessionId}/turns`))
    await page.getByRole('button', { name: '发送' }).click()
    await page.locator('.thinking-bubble').waitFor({ state: 'visible' })
    await turnRequestPromise
    await saveComposerScreenshot(page, 'feedback-question-composer-pending.png')
    await page.getByText('先对照冻结来源确认记录字段，再核对提交结果是否可复查。', { exact: true }).waitFor()
    const turn = apiAudit.writes.filter(item => item.path.endsWith('/turns')).at(-1)
    assert.equal(turn.path, `/api/tutor/sessions/${sessionId}/turns`)
    assert.deepEqual(turn.body.message, '请先给我一个方向')
    await saveScreenshot(page, 'feedback-question-tutor-reply-1301x871.png')
    await inspectTutor(page, 'feedback-question-reply-1301x871')
    await page.getByRole('button', { name: '关闭 Tutor' }).click()
    await page.locator('.tutor-panel').waitFor({ state: 'hidden' })
    const before = apiAudit.requests.filter(item => item.method === 'GET' && item.path === `/api/tutor/sessions/${sessionId}`).length
    await page.getByRole('button', { name: '需要提示' }).click()
    await page.getByText('请先给我一个方向', { exact: true }).waitFor()
    const after = apiAudit.requests.filter(item => item.method === 'GET' && item.path === `/api/tutor/sessions/${sessionId}`).length
    assert.equal(after, before + 1, 'question Tutor should restore the existing session when reopened')
    summary.checks.push({ name: 'question-session-restore', sessionId, before, after })
  } finally {
    await page.close()
  }
}

async function checkViewportLayout(label, viewport, { focus = false, mobile = false } = {}) {
  const page = await openPage(resourceRoute({ focus }), viewport)
  try {
    await waitForResource(page)
    await createResourceTutor(page)
    await page.locator('.tutor-welcome').waitFor()
    const check = await inspectTutor(page, label, { mobile })
    if (focus) {
      assert.equal(await page.locator('.tutor-panel').evaluate(panel => panel.classList.contains('is-embedded')), true,
        `${label}: focus mode should use the embedded Tutor panel`)
      assert.equal(await page.locator('.app-shell').count(), 0, 'focus resource mode should keep its immersive shell')
      check.embedded = true
    }
    await saveScreenshot(page, `${label}.png`)
  } finally {
    await page.close()
  }
}

async function checkKeyboardFocusAndReducedMotion() {
  const page = await openPage(resourceRoute(), { width: 390, height: 844 }, { reducedMotion: true })
  try {
    await waitForResource(page)
    await createResourceTutor(page)
    const textarea = page.locator('.tutor-panel textarea')
    await textarea.fill('键盘可达性')
    await textarea.focus()
    await page.keyboard.press('Tab')
    const focusState = await page.locator('.composer-send').evaluate(button => ({
      active: document.activeElement === button,
      focusVisible: button.matches(':focus-visible'),
      outlineStyle: getComputedStyle(button).outlineStyle,
      outlineWidth: getComputedStyle(button).outlineWidth,
      outlineColor: getComputedStyle(button).outlineColor,
    }))
    assert.equal(focusState.active, true, 'send control should be reachable by keyboard from the textarea')
    assert.equal(focusState.focusVisible, true, 'keyboard focused send control should expose focus-visible')
    assert.notEqual(focusState.outlineStyle, 'none', 'keyboard focus should have a visible outline')
    assert.ok(parseFloat(focusState.outlineWidth) >= 3, 'keyboard outline should be at least 3px')
    summary.checks.push({ name: 'keyboard-focus-ring', focusState })

    await textarea.fill('等待态与 reduced motion')
    await textarea.press('Enter')
    await page.locator('.thinking-bubble').waitFor({ state: 'visible' })
    const motion = await page.locator('.thinking-dots i').evaluateAll(nodes => nodes.map(node => ({
      animationDuration: getComputedStyle(node).animationDuration,
      transitionDuration: getComputedStyle(node).transitionDuration,
    })))
    assert.ok(motion.length >= 3)
    assert.ok(motion.every(item => item.animationDuration === '0s'), `reduced-motion should disable thinking animation: ${JSON.stringify(motion)}`)
    await page.getByText('先对照冻结来源确认记录字段，再核对提交结果是否可复查。', { exact: true }).waitFor()
    summary.checks.push({ name: 'reduced-motion', motion })
  } finally {
    await page.close()
  }
}

let thrown = null
try {
  browser = await chromium.launch(browserOptions('TUTOR_BROWSER_CHANNEL'))
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  serverStarted = true
  baseUrl = `http://127.0.0.1:${server.address().port}`

  log('start topbar route audit')
  await checkTopbarRoutes()
  log('start resource Tutor conversation audit')
  await checkResourceConversation()
  log('start feedback question Tutor audit')
  await checkQuestionTutorEntry()
  log('start viewport and focus-mode audit')
  await checkViewportLayout('resource-large-desktop-1886x1290', { width: 1886, height: 1290 })
  await checkViewportLayout('resource-phone-390x844', { width: 390, height: 844 }, { mobile: true })
  await checkViewportLayout('resource-phone-375x812', { width: 375, height: 812 }, { mobile: true })
  await checkViewportLayout('resource-short-window-375x520', { width: 375, height: 520 }, { mobile: true })
  await checkViewportLayout('resource-focus-1301x871', { width: 1301, height: 871 }, { focus: true })
  await checkKeyboardFocusAndReducedMotion()

  assert.deepEqual(topbarStyleViolations, [], `topbar style mismatch: ${JSON.stringify(topbarStyleViolations)}`)
  assert.deepEqual(layoutViolations, [], `Tutor layout mismatch: ${JSON.stringify(layoutViolations)}`)
  assert.deepEqual(apiAudit.unexpectedApi, [], `unexpected API requests: ${JSON.stringify(apiAudit.unexpectedApi)}`)
  assert.deepEqual(apiAudit.externalRequests, [], `external requests: ${JSON.stringify(apiAudit.externalRequests)}`)
  assert.deepEqual(apiAudit.pageErrors, [], `page errors: ${JSON.stringify(apiAudit.pageErrors)}`)
  assert.deepEqual(apiAudit.writes.filter(item => !item.allowed), [], 'only Tutor session and turn writes should be allowed')
  assert.ok(apiAudit.writes.length > 0)
  assert.ok(apiAudit.writes.every(item => item.path === '/api/tutor/sessions' || /\/api\/tutor\/sessions\/[^/]+\/(turns|close)$/.test(item.path)))
  summary.status = 'PASS'
  log('PASS tutor browser audit')
} catch (error) {
  thrown = error
  summary.status = 'FAIL'
  summary.failure = { message: error.message, stack: error.stack }
  log(`FAIL ${error.message}`)
} finally {
  summary.audit = apiAudit
  summary.topbarStyleViolations = topbarStyleViolations
  summary.layoutViolations = layoutViolations
  summary.summary = {
    browser: 'Playwright Chromium/Edge via browserOptions',
    screenshotCount: summary.screenshots.length,
    layoutCount: summary.layout.length,
    checkCount: summary.checks.length,
    topbarStyleViolationCount: topbarStyleViolations.length,
    layoutViolationCount: layoutViolations.length,
    writes: apiAudit.writes.map(item => ({ path: item.path, allowed: item.allowed })),
    unexpectedApiCount: apiAudit.unexpectedApi.length,
    externalRequestCount: apiAudit.externalRequests.length,
    pageErrorCount: apiAudit.pageErrors.length,
  }
  writeFileSync(path.join(evidenceDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
  writeFileSync(path.join(evidenceDir, 'run.log'), logLines.join('\n') + '\n')
  if (browser) await browser.close()
  if (serverStarted) await new Promise(resolve => server.close(resolve))
}
if (thrown) throw thrown
