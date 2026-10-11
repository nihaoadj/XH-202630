import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const reportDir = path.join(frontendDir, 'tests', 'test-results', 'onboarding-ui')
const summaryPath = path.join(reportDir, 'summary.json')

if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before onboarding browser test')
}
mkdirSync(reportDir, { recursive: true })

const viewports = [
  { name: 'desktop-1393x871', width: 1393, height: 871 },
  { name: 'desktop-1440x900', width: 1440, height: 900 },
  { name: 'tablet-1024x768', width: 1024, height: 768 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'mobile-375x667', width: 375, height: 667 },
  { name: 'landscape-844x390', width: 844, height: 390 },
  { name: 'short-desktop-1280x640', width: 1280, height: 640 },
]
const fitViewports = [
  { name: 'fit-1393x871', width: 1393, height: 871 },
  { name: 'fit-1440x900', width: 1440, height: 900 },
  { name: 'fit-1280x640', width: 1280, height: 640 },
  { name: 'fit-1886x1000', width: 1886, height: 1000 },
]

const questionnaire = [
  {
    question_id: 'q-experience',
    title: '你目前在临床数据分析方面处于什么阶段？',
    type: 'single_choice',
    required: true,
    hint: '选择最贴近当前实践情况的一项。',
    options: [
      { label: '正在入门，尚未参与项目', value: 'beginner' },
      { label: '有项目经验，正在处理复杂医疗数据', value: 'project-experience' },
      { label: '已能独立设计分析流程', value: 'independent' },
    ],
  },
  {
    question_id: 'q-goals',
    title: '本轮学习希望获得哪些能力？',
    type: 'multiple_choice',
    required: true,
    options: [
      { label: '案例拆解与复现', value: 'case-study' },
      { label: '数据质量控制', value: 'data-quality' },
      { label: '分析结果表达', value: 'communication' },
      { label: '在多中心、长周期临床数据中发现字段口径差异并形成可追溯的质量复核流程', value: 'cross-center-quality' },
    ],
  },
  {
    question_id: 'q-custom',
    title: '选择一个工作场景，也可以输入自定义场景',
    type: 'single_choice_or_other',
    required: false,
    options: [
      { label: '临床研究', value: 'clinical-research' },
      { label: '真实世界研究', value: 'real-world-evidence' },
    ],
  },
  {
    question_id: 'q-background',
    title: '请补充你的专业背景、当前项目与希望解决的问题',
    type: 'text',
    required: false,
    hint: '可以写下当前数据规模、团队协作方式或遇到的限制。',
  },
  {
    question_id: 'q-project-detail',
    title: '请描述一个正在处理的复杂医疗数据问题',
    type: 'text',
    required: false,
    show_when: { 'q-experience': { equals: 'project-experience' } },
  },
  {
    question_id: 'q-priority',
    title: '选择最优先解决的目标：在多中心、长周期项目中保证质量与可复现性',
    type: 'single_choice',
    required: false,
    options: [
      { label: '先建立数据校验与审计流程', value: 'quality-first' },
      { label: '先明确分析计划和协作接口', value: 'planning-first' },
    ],
  },
  {
    question_id: 'q-team',
    title: '你通常与哪些角色协作？',
    type: 'multiple_choice',
    required: false,
    options: ['临床研究者', '数据工程师', '统计师', '产品与运营', '医学信息与数据治理团队'],
  },
  {
    question_id: 'q-final-context',
    title: '还有哪些背景信息能帮助系统贴合你的实际工作？',
    type: 'text',
    required: false,
  },
]

const initialDiagnosticQuestions = [
  {
    question_id: 'diag-single',
    question_type: 'single_choice',
    question: '开始分析前，哪一步最有助于发现跨中心数据口径差异？',
    options: [
      '按统一字段字典逐一核查多个研究中心的原始来源和单位转换规则',
      '直接合并后再处理',
      '只检查总记录数',
    ],
  },
  {
    question_id: 'diag-multiple',
    question_type: 'multiple_choice',
    question: '哪些情况需要进入数据质量复核？',
    options: ['关键字段缺失', '同一患者记录冲突', '字段单位不一致'],
  },
  {
    question_id: 'diag-text',
    question_type: 'text',
    question: '你会如何记录一次数据清理决策及其影响？',
    options: [],
  },
]

const retestQuestions = [
  {
    question_id: 'diag-retest',
    question_type: 'single_choice',
    question: '复测：发现单位口径不一致后，下一步应如何处理？',
    options: ['确认来源并记录转换规则', '删除所有异常记录', '忽略差异继续分析'],
  },
]

const domainFixture = {
  domains: [
      {
      domain_id: 'domain-clinical',
      name: '临床研究与真实世界数据分析',
      description: '围绕研究设计、数据治理、稳健分析与结果表达建立可复现实践。',
      tracks: [
        {
          track_id: 'track-unavailable',
          knowledge_base_id: 'track-unavailable',
          name: '暂未开放的专科方向',
          description: '该方向当前没有可用的训练资料。',
          metadata: { available: false, document_count: 0, skill_node_count: 0 },
        },
        {
          track_id: 'track-main',
          knowledge_base_id: 'track-main',
          name: '临床数据分析与质量控制',
          description: '处理多中心、长周期、复杂口径数据时保持来源可追溯和结论可复现。',
          metadata: { available: true, document_count: 12, skill_node_count: 8 },
        },
        {
          track_id: 'track-secondary',
          knowledge_base_id: 'track-secondary',
          name: '研究方案设计与证据表达',
          description: '将研究问题、分析方法和结果解释组织成可审查的实践路径。',
          metadata: { available: true, document_count: 7, skill_node_count: 5 },
        },
      ],
    },
    {
      domain_id: 'domain-operations',
      name: '医疗运营与服务质量改进',
      description: '以实际服务流程和质量指标为基础，形成持续改进能力。',
      tracks: [
        {
          track_id: 'track-operations',
          knowledge_base_id: 'track-operations',
          name: '服务流程分析',
          description: '评估流程变化并持续跟踪服务质量。',
          metadata: { available: true, document_count: 4, skill_node_count: 3 },
        },
      ],
    },
    {
      domain_id: 'domain-ai',
      name: '人工智能应用与数据产品',
      description: '从实际业务问题出发，探索可靠的模型应用、评估与协作方法。',
      tracks: [
        {
          track_id: 'track-ai-apps',
          knowledge_base_id: 'track-ai-apps',
          name: '人工智能应用开发',
          description: '设计模型能力、业务流程与安全评估之间的有效协作。',
          metadata: { available: true, document_count: 9, skill_node_count: 6 },
        },
      ],
    },
    {
      domain_id: 'domain-engineering',
      name: '软件工程与质量保障',
      description: '围绕需求拆解、交付质量和系统维护建立工程实践。',
      tracks: [
        {
          track_id: 'track-software-quality',
          knowledge_base_id: 'track-software-quality',
          name: '软件质量与自动化验证',
          description: '把验证嵌入持续交付流程，提升变更可审查性。',
          metadata: { available: true, document_count: 6, skill_node_count: 4 },
        },
      ],
    },
  ],
}

const state = {
  scenario: 'primary',
  requests: [],
  writes: [],
  unexpectedApi: [],
  externalRequests: [],
  pageErrors: [],
  consoleErrors: [],
  failures: [],
  createdProfile: null,
  profileSuccessCount: 0,
  diagnosisSuccessCount: 0,
  generationSuccessCount: 0,
  failureRemaining: {},
  evidence: {
    status: 'RUNNING',
    browser: 'Playwright with browserOptions(ONBOARDING_BROWSER_CHANNEL)',
    viewports,
    viewportChecks: [],
    fitLayoutChecks: [],
    lockedScrollChecks: [],
    fallbackChecks: [],
    scrollChecks: [],
    containedScrollChecks: [],
    containedFallbackChecks: [],
    questionnaireChecks: [],
    diagnosisChecks: [],
    flowChecks: [],
    stageFocusChecks: [],
    loadingErrorChecks: [],
    payloadChecks: [],
    focusChecks: [],
    contrastChecks: [],
    reducedMotionChecks: [],
    browserErrors: [],
    failures: [],
    api: { requests: [], writes: [], unexpected: [] },
    screenshots: [],
  },
}

const resourceTypes = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const defaultResourceTypes = ['讲义', '实操指南', '分阶测试题']

function resetScenario(scenario) {
  state.scenario = scenario
  state.createdProfile = null
  state.profileSuccessCount = 0
  state.diagnosisSuccessCount = 0
  state.generationSuccessCount = 0
  state.failureRemaining = scenario === 'errors'
    ? { '/api/onboarding/initial-profile': 1, '/api/diagnosis/submit': 1, '/api/generate/jobs': 1 }
    : {}
}

function json(response, body, status = 200) {
  if (response.destroyed) return
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  response.end(JSON.stringify(body))
}

function delayedJson(response, body, delayMs, status = 200) {
  return new Promise((resolve) => setTimeout(() => {
    json(response, body, status)
    resolve()
  }, delayMs))
}

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return { raw }
  }
}

function userFixture() {
  return {
    user_id: 'onboarding-fixture-user',
    username: 'fixture-user',
    display_name: '工作台验收用户',
  }
}

function domainsResponse() {
  if (state.scenario === 'many-domains') {
    return {
      domains: Array.from({ length: 10 }, (_, index) => ({
        domain_id: 'domain-long-' + (index + 1),
        name: ('医疗研究与数据治理长期实践方向 ' + String(index + 1).padStart(2, '0') + ' · 临床质量与可复现分析').repeat(2),
        description: '围绕真实研究问题，整理多个中心、长期随访数据中的来源口径、质量审查和复核流程，保留可追踪依据并形成可复用的分析实践。'.repeat(2),
        tracks: [{
          track_id: 'track-long-' + (index + 1),
          knowledge_base_id: 'track-long-' + (index + 1),
          name: '长期数据分析训练方向',
          description: '以真实项目实践为核心。',
          metadata: { available: true, document_count: 5, skill_node_count: 4 },
        }],
      })),
    }
  }
  if (state.scenario === 'long-directions') {
    const domains = structuredClone(domainFixture)
    domains.domains[0].tracks = Array.from({ length: 4 }, (_, index) => ({
      track_id: 'track-long-description-' + (index + 1),
      knowledge_base_id: 'track-long-description-' + (index + 1),
      name: ('临床研究多中心长期数据质量与分析复核实践方向 ' + (index + 1)).repeat(2),
      description: ('在多中心协作与长期随访场景中，逐项核对字段定义、单位口径、缺失模式和来源差异；保留每次处理决策、复核记录及其对结果解释的影响，并组织团队完成可追踪、可复现的质量审查。').repeat(2),
      metadata: { available: true, document_count: 12 + index, skill_node_count: 8 + index },
    }))
    return domains
  }
  return structuredClone(domainFixture)
}

function questionsResponse() {
  return { learning_direction_id: 'track-main', questions: structuredClone(questionnaire) }
}

function profileFixture(learnerId, directionId = 'track-main') {
  return {
    learner_id: learnerId,
    user_id: 'onboarding-fixture-user',
    learner_type: '临床数据分析学习者',
    education: '研究生及以上',
    major: '临床研究与数据分析',
    target_domain: '临床研究与真实世界数据分析',
    knowledge_base_id: directionId,
    skill_level: '初级',
    weak_points: ['跨中心字段口径核对', '分析决策留痕'],
    strong_points: ['研究问题拆解'],
    knowledge_states: {},
    learning_goal: '建立可靠、可复现的临床数据分析流程',
    learning_preferences: { preferred_resource_types: defaultResourceTypes },
  }
}

function initialProfileResponse(payload) {
  const profile = profileFixture(payload?.learner_id || 'onboarding-fixture-user__track-main', payload?.learning_direction_id)
  state.createdProfile = profile
  const noQuestions = state.scenario === 'no-diagnosis'
  return {
    learner_id: profile.learner_id,
    profile,
    diagnostic_node_ids: noQuestions ? [] : ['node-data-quality'],
    not_started_node_ids: ['node-analysis-plan'],
    screening_results: {},
    diagnostic_questions: noQuestions ? [] : structuredClone(initialDiagnosticQuestions),
    questionnaire_tier: 1,
    initial_diagnostic_status: noQuestions ? 'final' : 'pending',
    next_step: noQuestions ? 'resource_selection' : 'initial_diagnosis',
  }
}

function diagnosisResponse(payload) {
  const successIndex = state.diagnosisSuccessCount
  state.diagnosisSuccessCount += 1
  if (state.scenario === 'primary' && successIndex === 0) {
    return {
      diagnostic_result_id: 'diagnostic-retest-fixture',
      learner_id: payload?.learner_id || state.createdProfile?.learner_id,
      knowledge_base_id: payload?.learning_direction_id || 'track-main',
      ability_level: '初级阶段校准中',
      weak_points: ['跨中心单位转换'],
      strong_points: ['数据质量意识'],
      knowledge_states: {},
      initial_diagnostic_status: 'retest',
      questionnaire_tier: 1,
      assessed_tier: 1,
      final_tier: 1,
      next_diagnostic_questions: structuredClone(retestQuestions),
    }
  }
  return {
    diagnostic_result_id: 'diagnostic-final-fixture',
    learner_id: payload?.learner_id || state.createdProfile?.learner_id,
    knowledge_base_id: payload?.learning_direction_id || 'track-main',
    ability_level: '初级',
    weak_points: ['跨中心字段口径核对', '分析决策留痕'],
    strong_points: ['研究问题拆解', '质量风险识别'],
    knowledge_states: {},
    initial_diagnostic_status: 'final',
    questionnaire_tier: 1,
    assessed_tier: 1,
    final_tier: 1,
    next_diagnostic_questions: [],
    initial_recommended_node_id: 'node-data-quality',
  }
}

function errorMessage(pathname) {
  if (pathname === '/api/onboarding/initial-profile') return '验收问卷提交失败，请稍后重试。'
  if (pathname === '/api/diagnosis/submit') return '验收诊断暂不可用，请稍后重试。'
  if (pathname === '/api/generate/jobs') return '验收生成服务暂不可用，请稍后重试。'
  return 'Fixture request failed'
}

async function apiResponse(url, method, request, response) {
  const pathname = url.pathname
  const body = ['GET', 'HEAD', 'OPTIONS'].includes(method) ? null : await readBody(request)
  const record = {
    scenario: state.scenario,
    method,
    path: pathname,
    query: url.search,
    body,
  }
  state.requests.push(record)

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    state.writes.push(record)
    if (!['/api/onboarding/initial-profile', '/api/diagnosis/submit', '/api/generate/jobs'].includes(pathname)) {
      state.unexpectedApi.push({ ...record, reason: 'Unexpected fixture write' })
      return json(response, { message: 'Unexpected fixture write rejected' }, 405)
    }
    if (state.failureRemaining[pathname] > 0) {
      state.failureRemaining[pathname] -= 1
      return delayedJson(response, { message: errorMessage(pathname) }, 260, 503)
    }
    if (pathname === '/api/onboarding/initial-profile') {
      state.profileSuccessCount += 1
      return delayedJson(response, initialProfileResponse(body), 300)
    }
    if (pathname === '/api/diagnosis/submit') {
      return delayedJson(response, diagnosisResponse(body), 300)
    }
    const index = state.generationSuccessCount
    state.generationSuccessCount += 1
    const runId = 'onboarding-fixture-run-' + state.scenario + '-' + (index + 1)
    return delayedJson(response, {
      status: 'success',
      run_id: runId,
      batch_id: runId,
      learner_id: body?.learner_id || state.createdProfile?.learner_id,
      topic: body?.topic || '临床数据分析',
      knowledge_base_id: body?.knowledge_base_id || 'track-main',
      job_status: 'queued',
    }, 300)
  }

  if (pathname === '/api/auth/me') return json(response, { user: userFixture() })
  if (pathname === '/api/knowledge/domains') return json(response, domainsResponse())
  if (pathname === '/api/onboarding/questions') return json(response, questionsResponse())
  if (pathname === '/api/skills/nodes') {
    return json(response, {
      knowledge_base_id: url.searchParams.get('knowledge_base_id') || 'track-main',
      nodes: [{ node_id: 'node-data-quality', name: '多中心数据口径核对', knowledge_base_id: 'track-main', tier: 1 }],
      edges: [],
    })
  }
  if (pathname === '/api/profiles/') {
    return json(response, {
      items: state.createdProfile ? [state.createdProfile] : [],
      total: state.createdProfile ? 1 : 0,
      page: 1,
      page_size: 50,
    })
  }
  if (pathname === '/api/generate/jobs') return json(response, { items: [] })
  if (pathname === '/api/resources/courseware/jobs') return json(response, { items: [] })

  state.unexpectedApi.push({ ...record, reason: 'Unexpected fixture API request' })
  return json(response, { detail: 'Unexpected fixture API request' }, 404)
}

function contentType(file) {
  return ({
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.ico': 'image/x-icon',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  })[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

function makeServer() {
  return createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://onboarding-fixture')
    const method = (request.method || 'GET').toUpperCase()
    if (url.pathname === '/__fixture/scenario') {
      resetScenario(url.searchParams.get('name') || 'primary')
      response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' })
      response.end('fixture scenario ready')
      return
    }
    if (url.pathname.startsWith('/api/')) {
      try {
        await apiResponse(url, method, request, response)
      } catch (error) {
        state.failures.push('Fixture API error: ' + error.message)
        if (!response.headersSent) json(response, { message: 'Fixture API error' }, 500)
        else response.destroy(error)
      }
      return
    }

    let decoded
    try {
      decoded = decodeURIComponent(url.pathname)
    } catch {
      response.writeHead(400)
      response.end('Invalid path')
      return
    }
    const candidate = path.resolve(distDir, '.' + decoded)
    const safe = candidate === distDir || candidate.startsWith(distDir + path.sep)
    const isFile = safe && existsSync(candidate) && statSync(candidate).isFile()
    const file = isFile ? candidate : path.join(distDir, 'index.html')
    if (!existsSync(file)) {
      response.writeHead(404)
      response.end('Not found')
      return
    }
    response.writeHead(200, { 'content-type': contentType(file), 'cache-control': 'no-cache' })
    response.end(readFileSync(file))
  })
}

function recordScreenshot(page, name) {
  const screenshotPath = path.join(reportDir, name + '.png')
  return page.screenshot({ path: screenshotPath, animations: 'disabled' }).then(() => {
    state.evidence.screenshots.push({ name, path: screenshotPath })
  })
}

async function createPage(browser, base, scenario, viewport = viewports[0]) {
  const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } })
  page.setDefaultTimeout(9000)
  page.setDefaultNavigationTimeout(12000)
  page.on('request', (request) => {
    try {
      if (new URL(request.url()).origin !== base) {
        state.externalRequests.push({ url: request.url(), method: request.method() })
      }
    } catch {
      state.externalRequests.push({ url: request.url(), method: request.method() })
    }
  })
  page.on('pageerror', (error) => {
    const item = { url: page.url(), message: error.message }
    state.pageErrors.push(item)
    state.evidence.browserErrors.push({ type: 'pageerror', ...item })
  })
  page.on('console', (message) => {
    if (message.type() === 'error') state.consoleErrors.push({ url: page.url(), message: message.text() })
  })
  await page.addInitScript(() => {
    const marker = '__onboarding_fixture_storage_initialized'
    if (sessionStorage.getItem(marker)) return
    localStorage.clear()
    sessionStorage.setItem(marker, '1')
  })
  await page.goto(base + '/__fixture/scenario?name=' + encodeURIComponent(scenario), { waitUntil: 'domcontentloaded' })
  await page.goto(base + '/learning/new', { waitUntil: 'domcontentloaded' })
  await page.locator('.domain-stage-card').waitFor()
  await page.locator('.choice-card').first().waitFor()
  return page
}

async function settle(page) {
  await page.evaluate(() => document.fonts.ready)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function settleLayout(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 90)))))
}

async function assertStageFocus(page, stageSelector, label) {
  await page.locator(stageSelector + ' .card-title').waitFor({ state: 'visible' })
  await page.waitForFunction((selector) => {
    const area = document.querySelector('.content-area')
    const title = document.querySelector(selector + ' .card-title')
    const card = document.querySelector(selector)
    const cardBody = card?.querySelector(':scope > .el-card__body')
    return area && title && document.activeElement === title && area.scrollTop === 0 && (!cardBody || cardBody.scrollTop === 0)
  }, stageSelector)
  const result = await page.evaluate((selector) => {
    const title = document.querySelector(selector + ' .card-title')
    const cardBody = document.querySelector(selector + ' > .el-card__body')
    return {
      tagName: title?.tagName || '',
      tabIndex: title?.getAttribute('tabindex'),
      focused: document.activeElement === title,
      scrollTop: document.querySelector('.content-area')?.scrollTop ?? -1,
      cardBodyScrollTop: cardBody?.scrollTop ?? 0,
    }
  }, stageSelector)
  assert.equal(result.tagName, 'H3', label + ': step heading should be an h3')
  assert.equal(result.tabIndex, '-1', label + ': step heading should not add a Tab stop')
  assert.equal(result.focused, true, label + ': focus should move to the new step heading')
  assert.equal(result.scrollTop, 0, label + ': step transition should reset content scroll to zero')
  assert.equal(result.cardBodyScrollTop, 0, label + ': step transition should reset the card body scroll to zero')
  state.evidence.stageFocusChecks.push({ label, stageSelector, ...result })
}

async function setSidebarState(page, collapsed) {
  const shell = page.locator('.app-shell')
  const isCollapsed = await shell.evaluate((node) => node.classList.contains('is-sidebar-collapsed'))
  if (isCollapsed !== collapsed) await page.locator('.sidebar-toggle').click()
  await page.waitForFunction((expected) => {
    const node = document.querySelector('.app-shell')
    return node && node.classList.contains('is-sidebar-collapsed') === expected
      && !node.classList.contains('is-sidebar-animating')
  }, collapsed)
  await settleLayout(page)
}

async function fitLayoutSnapshot(page, stageSelector, label) {
  const result = await page.evaluate((stage) => {
    const area = document.querySelector('.content-area')
    const root = document.querySelector('.onboarding-page')
    const grid = document.querySelector('.wizard-layout')
    const card = document.querySelector(stage)
    const required = [
      '.setup-intro', '.progress-panel', '.progress-footer',
      '.el-card__header', '.overview-strip',
      stage === '.domain-stage-card' ? '.domain-grid' : '.track-grid',
      '.insight-card', '.action-row', '.setup-footer',
    ]
    const bounds = required.map((selector) => {
      const node = card?.querySelector(selector) || root?.querySelector(selector)
      if (!node || node.getClientRects().length === 0) return { selector, missing: true }
      const rect = node.getBoundingClientRect()
      const areaRect = area.getBoundingClientRect()
      return {
        selector,
        top: rect.top,
        bottom: rect.bottom,
        areaTop: areaRect.top,
        areaBottom: areaRect.bottom,
        within: rect.top >= areaRect.top - 1 && rect.bottom <= areaRect.bottom + 1,
      }
    })
    const textSelectors = [
      '.setup-intro h2', '.setup-intro > p', '.progress-title', '.progress-desc',
      '.card-title', '.card-subtitle', '.choice-title', '.choice-description',
      '.choice-meta', '.insight-card p', '.action-hint', '.setup-footer span',
    ]
    const clippedText = textSelectors.flatMap((selector) => [...(root?.querySelectorAll(selector) || [])]
      .filter((node) => node.getClientRects().length > 0 && node.scrollHeight > node.clientHeight + 1)
      .map((node) => ({ selector, text: node.textContent.trim().slice(0, 80), scrollHeight: node.scrollHeight, clientHeight: node.clientHeight })))
    const action = card?.querySelector('.action-row .el-button--primary')
    const actionRect = action?.getBoundingClientRect()
    const hiddenOverflows = [root, grid, document.querySelector('.progress-panel'), card]
      .filter((node) => node && node.scrollHeight > node.clientHeight + 1 && ['hidden', 'clip'].includes(getComputedStyle(node).overflowY))
      .map((node) => ({ className: node.className, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight, overflowY: getComputedStyle(node).overflowY }))
    return {
      fit: root?.classList.contains('is-fit-layout') || false,
      overflowY: area ? getComputedStyle(area).overflowY : '',
      contentArea: area ? {
        clientWidth: area.clientWidth,
        scrollWidth: area.scrollWidth,
        clientHeight: area.clientHeight,
        scrollHeight: area.scrollHeight,
        scrollTop: area.scrollTop,
      } : null,
      bounds,
      clippedText,
      hiddenOverflows,
      actionBottom: actionRect?.bottom ?? null,
      bodyScrollTop: document.scrollingElement?.scrollTop ?? 0,
    }
  }, stageSelector)
  assert.ok(result.fit, label + ': expected measured one-screen fit mode')
  assert.ok(['hidden', 'clip'].includes(result.overflowY), label + ': fit mode should lock the shared content area')
  assert.ok(result.contentArea.scrollHeight <= result.contentArea.clientHeight + 1, label + ': measured content does not fit in the locked area')
  assert.equal(result.contentArea.scrollTop, 0, label + ': fit layout must begin at scrollTop zero')
  assert.equal(result.bodyScrollTop, 0, label + ': root page should not scroll in fit mode')
  assert.deepEqual(result.bounds.filter((item) => item.missing || !item.within), [], label + ': a required section is clipped outside the visible content boundary')
  assert.deepEqual(result.clippedText, [], label + ': text is clipped in fit mode')
  assert.deepEqual(result.hiddenOverflows, [], label + ': a fit-mode container clips content')
  assert.ok(result.actionBottom <= result.bounds[0].areaBottom + 1, label + ': bottom action is outside the visible content boundary')
  state.evidence.fitLayoutChecks.push({ label, stageSelector, ...result })
  return result
}

async function assertFitScrollLocked(page, stageSelector, label) {
  const title = page.locator(stageSelector + ' .card-title')
  await title.evaluate((node) => node.focus({ preventScroll: true }))
  const areaBox = await page.locator('.content-area').boundingBox()
  assert.ok(areaBox, label + ': missing content area for scroll input')
  await page.mouse.move(areaBox.x + areaBox.width * 0.7, areaBox.y + areaBox.height * 0.55)
  await page.mouse.wheel(0, 620)
  await settleLayout(page)
  const wheel = await page.locator('.content-area').evaluate((node) => node.scrollTop)
  assert.equal(wheel, 0, label + ': wheel input changed the locked scroll position')

  await page.keyboard.press('PageDown')
  await settleLayout(page)
  const pageDown = await page.locator('.content-area').evaluate((node) => node.scrollTop)
  assert.equal(pageDown, 0, label + ': PageDown changed the locked scroll position')

  await page.keyboard.press('Space')
  await settleLayout(page)
  const space = await page.locator('.content-area').evaluate((node) => node.scrollTop)
  assert.equal(space, 0, label + ': Space changed the locked scroll position')

  await page.evaluate(() => {
    const area = document.querySelector('.content-area')
    area.scrollTop = 180
    window.scrollTo(0, 180)
  })
  await settleLayout(page)
  const programmatic = await page.evaluate(() => ({
    areaScrollTop: document.querySelector('.content-area').scrollTop,
    documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
  }))
  assert.equal(programmatic.areaScrollTop, 0, label + ': programmatic scrollTop changed the locked content position')
  assert.equal(programmatic.documentScrollTop, 0, label + ': programmatic window scroll moved the root page')
  state.evidence.lockedScrollChecks.push({ label, wheel, pageDown, space, ...programmatic })
}

async function assertNaturalStageScroll(page, stageSelector, lastItemSelector, label) {
  const result = await page.evaluate(({ stage, lastSelector }) => {
    const area = document.querySelector('.content-area')
    const root = document.querySelector('.onboarding-page')
    const card = document.querySelector(stage)
    const lastItem = card?.querySelector(lastSelector)
    const action = card?.querySelector('.action-row .el-button--primary')
    const scrollHeight = area?.scrollHeight ?? 0
    if (area) area.scrollTop = Math.max(0, scrollHeight - area.clientHeight)
    const areaRect = area?.getBoundingClientRect()
    const lastRect = lastItem?.getBoundingClientRect()
    const actionRect = action?.getBoundingClientRect()
    const clippedText = [...(root?.querySelectorAll('.choice-title,.choice-description,.choice-meta') || [])]
      .filter((node) => node.getClientRects().length > 0 && node.scrollWidth > node.clientWidth + 1)
      .map((node) => ({ text: node.textContent.trim().slice(0, 80), scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }))
    return {
      fit: root?.classList.contains('is-fit-layout') || false,
      overflowY: area ? getComputedStyle(area).overflowY : '',
      clientHeight: area?.clientHeight ?? 0,
      scrollHeight,
      scrollTop: area?.scrollTop ?? -1,
      lastItemVisible: Boolean(areaRect && lastRect && lastRect.bottom <= areaRect.bottom + 1),
      actionVisible: Boolean(areaRect && actionRect && actionRect.bottom <= areaRect.bottom + 1),
      bodyScrollTop: document.scrollingElement?.scrollTop ?? 0,
      clippedText,
    }
  }, { stage: stageSelector, lastSelector: lastItemSelector })
  assert.equal(result.fit, false, label + ': oversized content should use natural scrolling')
  assert.ok(['auto', 'scroll'].includes(result.overflowY), label + ': natural mode should leave the content area scrollable')
  assert.ok(result.scrollHeight > result.clientHeight, label + ': expected the content to exceed the viewport')
  assert.ok(result.scrollTop > 0, label + ': content area should reach its lower content')
  assert.ok(result.lastItemVisible, label + ': final choice is not reachable at the end of content')
  assert.ok(result.actionVisible, label + ': final primary action is not reachable at the end of content')
  assert.equal(result.bodyScrollTop, 0, label + ': page/root should remain fixed while content area scrolls')
  assert.deepEqual(result.clippedText, [], label + ': long choice text is clipped instead of wrapping')
  state.evidence.fallbackChecks.push({ label, stageSelector, ...result })
}

async function verifyFitMatrix(page) {
  for (const viewport of fitViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await settleLayout(page)
    await page.waitForFunction(() => document.querySelector('.onboarding-page')?.classList.contains('is-fit-layout'))
    for (const collapsed of [false, true]) {
      await setSidebarState(page, collapsed)
      const stateLabel = collapsed ? 'collapsed' : 'expanded'
      const label = viewport.name + ' domain ' + stateLabel
      await fitLayoutSnapshot(page, '.domain-stage-card', label)
      await assertFitScrollLocked(page, '.domain-stage-card', label)
    }
  }

  await setSidebarState(page, false)
  await page.locator('.domain-stage-card .choice-card').first().click()
  await page.getByRole('button', { name: '下一步' }).click()
  await assertStageFocus(page, '.track-stage-card', 'domain to track during fit matrix')

  for (const viewport of fitViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await settleLayout(page)
    await page.waitForFunction(() => document.querySelector('.onboarding-page')?.classList.contains('is-fit-layout'))
    for (const collapsed of [false, true]) {
      await setSidebarState(page, collapsed)
      const stateLabel = collapsed ? 'collapsed' : 'expanded'
      const label = viewport.name + ' track ' + stateLabel
      await fitLayoutSnapshot(page, '.track-stage-card', label)
      await assertFitScrollLocked(page, '.track-stage-card', label)
    }
  }
  await setSidebarState(page, false)
  await page.locator('.progress-card').nth(0).click()
  await assertStageFocus(page, '.domain-stage-card', 'track to domain during fit matrix')
}

async function assertLayout(page, viewport, label, { primary = true } = {}) {
  const result = await page.evaluate(() => {
    const selectors = [
      '.onboarding-page', '.wizard-layout', '.step-panel',
      '.domain-stage-card', '.track-stage-card', '.questionnaire-stage-card',
      '.diagnosis-stage-card', '.review-stage-card', '.choice-card', '.question-block',
      '.action-row',
    ]
    const overflowing = []
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const style = getComputedStyle(node)
        if (style.display === 'none' || node.getClientRects().length === 0) continue
        if (node.scrollWidth > node.clientWidth + 1) {
          overflowing.push({ selector, text: (node.textContent || '').trim().slice(0, 60), clientWidth: node.clientWidth, scrollWidth: node.scrollWidth })
        }
      }
    }
    const area = document.querySelector('.content-area')
    const primaryButton = document.querySelector('.action-row .el-button--primary')
    const buttonRect = primaryButton?.getBoundingClientRect()
    return {
      innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      contentArea: area ? {
        clientWidth: area.clientWidth,
        scrollWidth: area.scrollWidth,
        clientHeight: area.clientHeight,
        scrollHeight: area.scrollHeight,
        overflowY: getComputedStyle(area).overflowY,
      } : null,
      overflowing,
      primaryButtonHeight: buttonRect?.height ?? null,
      cardSelectors: selectors.slice(3, 8).filter((selector) => document.querySelector(selector)),
    }
  })
  assert.ok(result.documentWidth <= viewport.width + 1, label + ': document has horizontal overflow ' + JSON.stringify(result))
  assert.ok(result.bodyWidth <= viewport.width + 1, label + ': body has horizontal overflow ' + JSON.stringify(result))
  assert.deepEqual(result.overflowing, [], label + ': onboarding content has horizontal overflow')
  assert.ok(result.contentArea, label + ': missing shared .content-area scroll container')
  assert.ok(result.contentArea.scrollWidth <= result.contentArea.clientWidth + 1, label + ': main content area has horizontal overflow')
  if (primary) assert.ok(result.primaryButtonHeight >= 43, label + ': primary action is below 44px target height')
  state.evidence.viewportChecks.push({ label, viewport: viewport.name, ...result })
  return result
}

async function assertOptionWrap(page, selector, expectedText, label) {
  const target = page.locator(selector).filter({ hasText: expectedText }).first()
  await target.waitFor({ state: 'visible' })
  const result = await target.evaluate((node) => {
    const range = document.createRange()
    range.selectNodeContents(node)
    const rect = node.getBoundingClientRect()
    const style = getComputedStyle(node)
    return {
      text: node.textContent.trim(),
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
      height: rect.height,
      lineHeight: Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.3,
      whiteSpace: style.whiteSpace,
      textLineFragments: range.getClientRects().length,
    }
  })
  assert.ok(result.clientWidth > 0, label + ': option label has no visible width')
  assert.ok(result.scrollWidth <= result.clientWidth + 1, label + ': option label is horizontally clipped: ' + JSON.stringify(result))
  assert.notEqual(result.whiteSpace, 'nowrap', label + ': option label is forced onto one clipped line')
  assert.ok(result.textLineFragments >= 2 || result.height >= result.lineHeight * 1.65, label + ': long option label did not wrap onto multiple lines')
  state.evidence.questionnaireChecks.push({ label, optionWrap: result })
}

async function assertContainedFormScroll(page, stageSelector, label, { exerciseWheel = false, exerciseKeyboard = false, screenshotPrefix = '' } = {}) {
  const initial = await page.evaluate((stage) => {
    const root = document.querySelector('.onboarding-page')
    const area = document.querySelector('.content-area')
    const card = document.querySelector(stage)
    const body = card?.querySelector(':scope > .el-card__body')
    if (body) body.scrollTop = 0
    const fixedSelectors = ['.setup-intro', '.progress-panel', '.progress-list', '.progress-card.active']
    if (innerWidth > 1080) fixedSelectors.push('.progress-footer')
    fixedSelectors.push('.setup-footer')
    const fixedRects = fixedSelectors.map((selector) => {
      const node = root?.querySelector(selector)
      if (!node || node.getClientRects().length === 0) return { selector, missing: true }
      const rect = node.getBoundingClientRect()
      return { selector, top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }
    })
    const header = card?.querySelector(':scope > .el-card__header')
    if (header) {
      const rect = header.getBoundingClientRect()
      fixedRects.push({ selector: '.work-card > .el-card__header', top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right })
    }
    const style = body ? getComputedStyle(body) : null
    const areaStyle = area ? getComputedStyle(area) : null
    const maxScroll = body ? Math.max(0, body.scrollHeight - body.clientHeight) : 0
    const otherScrollers = [...(card?.querySelectorAll('*') || [])]
      .filter((node) => node !== body)
      .filter((node) => {
        const candidateStyle = getComputedStyle(node)
        return node.scrollHeight > node.clientHeight + 1 && ['auto', 'scroll'].includes(candidateStyle.overflowY)
      })
      .map((node) => ({ selector: node.className?.baseVal || node.className || node.tagName.toLowerCase(), overflowY: getComputedStyle(node).overflowY }))
    return {
      contained: root?.classList.contains('is-contained-layout') || false,
      contentArea: area ? {
        overflowY: areaStyle.overflowY,
        clientHeight: area.clientHeight,
        scrollHeight: area.scrollHeight,
        scrollTop: area.scrollTop,
      } : null,
      body: body ? {
        overflowY: style.overflowY,
        overscrollBehaviorY: style.overscrollBehaviorY,
        role: body.getAttribute('role'),
        tabIndex: body.getAttribute('tabindex'),
        ariaLabel: body.getAttribute('aria-label'),
        clientHeight: body.clientHeight,
        scrollHeight: body.scrollHeight,
        scrollTop: body.scrollTop,
        maxScroll,
        scrollWidth: body.scrollWidth,
        clientWidth: body.clientWidth,
      } : null,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
      fixedRects,
      otherScrollers,
    }
  }, stageSelector)
  const evidenceEntry = { label, stageSelector, ...initial, complete: false }
  state.evidence.containedScrollChecks.push(evidenceEntry)
  assert.equal(initial.contained, true, label + ': form stage should lock its outer layout')
  assert.ok(initial.contentArea, label + ': missing shared content area')
  assert.ok(['hidden', 'clip'].includes(initial.contentArea.overflowY), label + ': contained mode should lock the outer content area')
  assert.equal(initial.contentArea.scrollTop, 0, label + ': outer content area should remain at scrollTop zero')
  assert.ok(initial.contentArea.scrollHeight <= initial.contentArea.clientHeight + 1, label + ': the outer content area should not contain the form overflow')
  assert.ok(initial.body, label + ': missing direct .work-card > .el-card__body scroll region')
  assert.ok(['auto', 'scroll'].includes(initial.body.overflowY), label + ': only the card body should own vertical scrolling')
  assert.equal(initial.body.overscrollBehaviorY, 'contain', label + ': card body should contain scroll chaining')
  const stageLabels = {
    '.questionnaire-stage-card': '问卷内容',
    '.diagnosis-stage-card': '诊断题目',
    '.review-stage-card': '资源确认内容',
  }
  assert.equal(initial.body.role, 'region', label + ': card body should be a named region')
  assert.equal(initial.body.tabIndex, '0', label + ': card body should be keyboard focusable')
  assert.equal(initial.body.ariaLabel, stageLabels[stageSelector], label + ': card body should have a stage-specific accessible name')
  assert.ok(initial.body.clientHeight >= 80, label + ': a contained layout must leave at least 80px for the card body')
  assert.ok(initial.body.maxScroll > 0, label + ': form content should overflow the card body')
  assert.ok(initial.body.scrollWidth <= initial.body.clientWidth + 1, label + ': card body has horizontal overflow')
  assert.equal(initial.documentScrollTop, 0, label + ': document/root should not scroll')
  assert.deepEqual(initial.fixedRects.filter((item) => item.missing), [], label + ': expected fixed regions should remain present')
  assert.deepEqual(initial.otherScrollers, [], label + ': the card body must be the only inner scroll region')
  if (screenshotPrefix) await recordScreenshot(page, screenshotPrefix + '-top')

  const bottom = await page.locator(stageSelector).evaluate((card) => {
    const body = card.querySelector(':scope > .el-card__body')
    const action = card.querySelector('.action-row .el-button--primary')
    const lastQuestion = card.querySelector('.question-block[data-question-id="q-final-context"]')
      || card.querySelector('.diagnostic-item:last-of-type')
      || card.querySelector('.supplemental-field')
    if (!body || !action) return { missing: true }
    body.scrollTop = 0
    let lastRect = lastQuestion?.getBoundingClientRect()
    // A tall question can span several scroll positions on a short phone.
    // Its label and each control must be independently fully reachable.
    const lastParts = lastRect && lastRect.height > body.clientHeight
      ? [...lastQuestion.querySelectorAll('.el-form-item__label, .question-title, textarea, input')]
        .filter((node) => node.getClientRects().length > 0)
      : lastQuestion ? [lastQuestion] : []
    const lastContentChecks = lastParts.map((node) => {
      const bounds = body.getBoundingClientRect()
      let rect = node.getBoundingClientRect()
      if (rect.top < bounds.top) body.scrollTop -= bounds.top - rect.top
      else if (rect.bottom > bounds.bottom) body.scrollTop += rect.bottom - bounds.bottom
      rect = node.getBoundingClientRect()
      return {
        tag: node.tagName,
        className: node.className,
        top: rect.top,
        bottom: rect.bottom,
        scrollTop: body.scrollTop,
        visible: rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1,
      }
    })
    const lastContentVisible = !lastQuestion || lastContentChecks.length > 0 && lastContentChecks.every((part) => part.visible)
    lastRect = lastQuestion?.getBoundingClientRect()
    const lastContentScrollTop = body.scrollTop
    body.scrollTop = body.scrollHeight
    const bodyRect = body.getBoundingClientRect()
    const actionRect = action.getBoundingClientRect()
    const fixedSelectors = ['.setup-intro', '.progress-panel', '.progress-list', '.progress-card.active']
    if (innerWidth > 1080) fixedSelectors.push('.progress-footer')
    fixedSelectors.push('.setup-footer')
    const fixedRects = fixedSelectors.map((selector) => {
      const node = document.querySelector('.onboarding-page ' + selector)
      const rect = node?.getBoundingClientRect()
      return { selector, top: rect?.top, bottom: rect?.bottom, left: rect?.left, right: rect?.right }
    })
    const header = card.querySelector(':scope > .el-card__header')
    const headerRect = header?.getBoundingClientRect()
    fixedRects.push({ selector: '.work-card > .el-card__header', top: headerRect?.top, bottom: headerRect?.bottom, left: headerRect?.left, right: headerRect?.right })
    return {
      scrollTop: body.scrollTop,
      maxScroll: Math.max(0, body.scrollHeight - body.clientHeight),
      actionVisible: actionRect.top >= bodyRect.top - 1 && actionRect.bottom <= bodyRect.bottom + 1,
      lastContentVisible,
      lastContentChecks,
      lastContentScrollTop,
      lastContentRect: lastRect ? { top: lastRect.top, bottom: lastRect.bottom } : null,
      bodyRect: { top: bodyRect.top, bottom: bodyRect.bottom },
      actionRect: { top: actionRect.top, bottom: actionRect.bottom },
      fixedRects,
      outerScrollTop: document.querySelector('.content-area')?.scrollTop ?? -1,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
    }
  })
  evidenceEntry.bottom = bottom
  if (screenshotPrefix) await recordScreenshot(page, screenshotPrefix + '-bottom')
  assert.notEqual(bottom.missing, true, label + ': missing inner body or primary action')
  assert.ok(bottom.scrollTop >= bottom.maxScroll - 1, label + ': card body did not reach its lower content')
  assert.ok(bottom.actionVisible, label + ': primary action is unreachable within the card body')
  assert.ok(bottom.lastContentVisible, label + ': final stage content is unreachable within the card body')
  assert.equal(bottom.outerScrollTop, 0, label + ': inner scroll should not move the outer content area')
  assert.equal(bottom.documentScrollTop, 0, label + ': inner scroll should not move the document')
  for (const before of initial.fixedRects) {
    const after = bottom.fixedRects.find((item) => item.selector === before.selector)
    assert.ok(after, label + ': fixed region disappeared during body scrolling: ' + before.selector)
    for (const key of ['top', 'bottom', 'left', 'right']) {
      assert.ok(Math.abs(before[key] - after[key]) <= 1, label + ': fixed region moved during body scrolling: ' + before.selector + ' ' + key)
    }
  }
  let wheel = null
  let edgeWheel = null
  let keyboard = null
  if (exerciseWheel) {
    await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => { body.scrollTop = 0 })
    const box = await page.locator(stageSelector + ' > .el-card__body').boundingBox()
    assert.ok(box && box.height >= 80, label + ': missing usable card body for wheel input')
    await page.mouse.move(box.x + box.width * 0.6, box.y + Math.min(box.height / 2, 60))
    await page.mouse.wheel(0, Math.max(420, box.height))
    await settleLayout(page)
    wheel = await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => ({
      scrollTop: body.scrollTop,
      maxScroll: Math.max(0, body.scrollHeight - body.clientHeight),
      outerScrollTop: document.querySelector('.content-area')?.scrollTop ?? -1,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
    }))
    assert.ok(wheel.scrollTop > 0, label + ': wheel should scroll the card body')
    assert.equal(wheel.outerScrollTop, 0, label + ': wheel should not scroll the outer content area')
    assert.equal(wheel.documentScrollTop, 0, label + ': wheel should not scroll the document')
    evidenceEntry.wheel = wheel
    await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => { body.scrollTop = body.scrollHeight })
    const endBox = await page.locator(stageSelector + ' > .el-card__body').boundingBox()
    await page.mouse.move(endBox.x + endBox.width * 0.6, endBox.y + Math.min(endBox.height / 2, 60))
    await page.mouse.wheel(0, 16000)
    await settleLayout(page)
    edgeWheel = await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => ({
      scrollTop: body.scrollTop,
      maxScroll: Math.max(0, body.scrollHeight - body.clientHeight),
      outerScrollTop: document.querySelector('.content-area')?.scrollTop ?? -1,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
    }))
    assert.ok(edgeWheel.scrollTop >= edgeWheel.maxScroll - 1, label + ': body should remain at its lower edge')
    assert.equal(edgeWheel.outerScrollTop, 0, label + ': overscrolled body should not chain into the outer content area')
    assert.equal(edgeWheel.documentScrollTop, 0, label + ': overscrolled body should not chain into the document')
    evidenceEntry.edgeWheel = edgeWheel
  }
  if (exerciseKeyboard) {
    await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => { body.scrollTop = 0 })
    await page.locator(stageSelector + ' .card-title').focus()
    await page.keyboard.press('Tab')
    const focused = await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => ({
      active: document.activeElement === body,
      focusVisible: body.matches(':focus-visible'),
      outlineStyle: getComputedStyle(body).outlineStyle,
      outlineWidth: getComputedStyle(body).outlineWidth,
    }))
    assert.equal(focused.active, true, label + ': Tab should move focus into the card body region')
    assert.equal(focused.focusVisible, true, label + ': keyboard focus on the card body should be visible')
    assert.ok(focused.outlineStyle !== 'none' && Number.parseFloat(focused.outlineWidth) >= 2, label + ': card body focus ring should have a visible 2px outline')
    await page.keyboard.press('PageDown')
    await settleLayout(page)
    keyboard = await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => ({
      scrollTop: body.scrollTop,
      maxScroll: Math.max(0, body.scrollHeight - body.clientHeight),
      outerScrollTop: document.querySelector('.content-area')?.scrollTop ?? -1,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
      focusVisible: body.matches(':focus-visible'),
      outlineStyle: getComputedStyle(body).outlineStyle,
      outlineWidth: getComputedStyle(body).outlineWidth,
    }))
    assert.ok(keyboard.scrollTop > 0, label + ': PageDown should scroll the focused card body')
    assert.equal(keyboard.outerScrollTop, 0, label + ': PageDown should not scroll the outer content area')
    assert.equal(keyboard.documentScrollTop, 0, label + ': PageDown should not scroll the document')
    assert.equal(keyboard.focusVisible, true, label + ': card body focus ring should remain visible while scrolling')
    assert.ok(keyboard.outlineStyle !== 'none' && Number.parseFloat(keyboard.outlineWidth) >= 2, label + ': keyboard scrolling should retain the visible outline')
    evidenceEntry.keyboard = { ...focused, ...keyboard }
  }
  await page.locator(stageSelector + ' > .el-card__body').evaluate((body) => { body.scrollTop = 0 })
  evidenceEntry.complete = true
  return { initial, bottom, wheel, edgeWheel, keyboard }
}

async function assertReachableContent(page, label, { lastQuestion = false } = {}) {
  const result = await page.evaluate((needQuestion) => {
    const area = document.querySelector('.content-area')
    const root = document.querySelector('.onboarding-page')
    const card = document.querySelector('.questionnaire-stage-card, .diagnosis-stage-card, .review-stage-card')
    const contained = root?.classList.contains('is-contained-layout') || false
    const cardBody = card?.querySelector(':scope > .el-card__body')
    const scroller = contained ? cardBody : area
    const action = card?.querySelector('.action-row .el-button--primary')
    const last = needQuestion ? card?.querySelector('.question-block[data-question-id="q-final-context"]') : null
    const innerScrollers = [...(card?.querySelectorAll('*') || [])]
      .filter((node) => node !== cardBody)
      .filter((node) => {
        const style = getComputedStyle(node)
        return node.scrollHeight > node.clientHeight + 1 && ['auto', 'scroll'].includes(style.overflowY)
      })
    if (!area || !card || !action || !scroller) return { missing: true }
    const before = scroller.scrollTop
    const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    scroller.scrollTop = 0
    let lastRect = last?.getBoundingClientRect()
    const lastParts = lastRect && lastRect.height > scroller.clientHeight
      ? [...last.querySelectorAll('.el-form-item__label, textarea, input')]
        .filter((node) => node.getClientRects().length > 0)
      : last ? [last] : []
    const lastQuestionChecks = lastParts.map((node) => {
      const bounds = scroller.getBoundingClientRect()
      let rect = node.getBoundingClientRect()
      if (rect.top < bounds.top) scroller.scrollTop -= bounds.top - rect.top
      else if (rect.bottom > bounds.bottom) scroller.scrollTop += rect.bottom - bounds.bottom
      rect = node.getBoundingClientRect()
      return {
        tag: node.tagName,
        top: rect.top,
        bottom: rect.bottom,
        scrollTop: scroller.scrollTop,
        visible: rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1,
      }
    })
    const lastQuestionVisible = !last || lastQuestionChecks.length > 0 && lastQuestionChecks.every((part) => part.visible)
    lastRect = last?.getBoundingClientRect()
    const lastQuestionScrollTop = scroller.scrollTop
    scroller.scrollTop = maxScroll
    const scrollerRect = scroller.getBoundingClientRect()
    const areaStyle = getComputedStyle(area)
    const bodyStyle = cardBody ? getComputedStyle(cardBody) : null
    const actionRect = action.getBoundingClientRect()
    return {
      scrollMode: contained ? 'card-body' : 'content-area',
      fit: [...document.querySelectorAll('.onboarding-page,.wizard-layout,.questionnaire-stage-card,.review-stage-card')]
        .some((node) => node.classList.contains('is-fit-layout')),
      overflowY: contained ? bodyStyle.overflowY : areaStyle.overflowY,
      outerOverflowY: areaStyle.overflowY,
      before,
      maxScroll,
      after: scroller.scrollTop,
      areaHeight: scroller.clientHeight,
      scrollHeight: scroller.scrollHeight,
      actionBottom: actionRect.bottom,
      actionVisible: actionRect.top >= scrollerRect.top - 1 && actionRect.bottom <= scrollerRect.bottom + 1,
      lastQuestionBottom: lastRect?.bottom ?? null,
      lastQuestionVisible,
      lastQuestionChecks,
      lastQuestionScrollTop,
      bodyScrollTop: document.scrollingElement?.scrollTop ?? 0,
      outerScrollTop: area.scrollTop,
      cardBodyClientHeight: cardBody?.clientHeight ?? 0,
      cardBodyScrollHeight: cardBody?.scrollHeight ?? 0,
      cardBodyOverscrollBehaviorY: bodyStyle?.overscrollBehaviorY ?? '',
      innerScrollers: innerScrollers.map((node) => ({ className: node.className, overflowY: getComputedStyle(node).overflowY })),
    }
  }, lastQuestion)
  assert.notEqual(result.missing, true, label + ': missing scroll target or primary action')
  assert.equal(result.fit, false, label + ': long questionnaire/review should remain naturally scrollable')
  if (result.scrollMode === 'card-body') {
    assert.ok(['hidden', 'clip'].includes(result.outerOverflowY), label + ': contained form should lock the outer content area')
    assert.equal(result.outerScrollTop, 0, label + ': contained form should keep the outer content area at zero')
    assert.ok(['auto', 'scroll'].includes(result.overflowY), label + ': contained form should scroll its card body')
    assert.equal(result.cardBodyOverscrollBehaviorY, 'contain', label + ': contained card body should prevent scroll chaining')
  } else {
    assert.ok(['auto', 'scroll'].includes(result.overflowY), label + ': natural fallback should use the shared content area')
  }
  assert.ok(result.maxScroll > 0, label + ': expected the content area to scroll')
  assert.ok(result.after >= result.maxScroll - 1, label + ': form content did not reach its end')
  assert.ok(result.actionVisible, label + ': primary action is unreachable at the end of content')
  if (lastQuestion) assert.ok(result.lastQuestionVisible, label + ': final question is unreachable')
  assert.equal(result.bodyScrollTop, 0, label + ': page/root scrolled instead of the form region')
  assert.deepEqual(result.innerScrollers, [], label + ': the form card contains another scroll region')
  if (result.scrollMode === 'card-body') state.evidence.containedScrollChecks.push({ label, kind: 'reachable-content', ...result })
  else state.evidence.containedFallbackChecks.push({ label, kind: 'reachable-content', ...result })
  state.evidence.scrollChecks.push({ label, ...result })
  return result
}

async function verifyContainedQuestionnaireMatrix(page) {
  const desktopViewports = [
    { name: 'contained-1331x871', width: 1331, height: 871 },
    { name: 'contained-1393x871', width: 1393, height: 871 },
    { name: 'contained-1280x640', width: 1280, height: 640 },
  ]
  for (const viewport of desktopViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await settleLayout(page)
    await page.waitForFunction(() => document.querySelector('.onboarding-page')?.classList.contains('is-contained-layout'))
    for (const collapsed of [false, true]) {
      await setSidebarState(page, collapsed)
      const stateLabel = collapsed ? 'collapsed' : 'expanded'
      const screenshotPrefix = collapsed || viewport.name === 'contained-1280x640'
        ? ''
        : '06-questionnaire-' + viewport.name
      await assertContainedFormScroll(
        page,
        '.questionnaire-stage-card',
        viewport.name + ' questionnaire ' + stateLabel,
        {
          exerciseWheel: viewport.name === 'contained-1331x871' && !collapsed,
          exerciseKeyboard: viewport.name === 'contained-1393x871' && !collapsed,
          screenshotPrefix,
        },
      )
    }
  }

  const tabletMobileViewports = [viewports[2], viewports[3], viewports[4], viewports[5]]
  for (const viewport of tabletMobileViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await settleLayout(page)
    await page.waitForFunction(() => document.querySelector('.onboarding-page')?.classList.contains('is-contained-layout'))
    const mobileScreenshot = ['mobile-390x844', 'mobile-375x667'].includes(viewport.name)
      ? '06-questionnaire-contained-' + viewport.name
      : ''
    await assertContainedFormScroll(page, '.questionnaire-stage-card', viewport.name + ' questionnaire contained', {
      exerciseWheel: viewport.name === 'mobile-375x667',
      screenshotPrefix: mobileScreenshot,
    })
  }

  const shortLandscape = viewports.find((viewport) => viewport.name === 'landscape-844x390')
  await page.setViewportSize({ width: shortLandscape.width, height: shortLandscape.height })
  await settleLayout(page)
  const isContained = await page.locator('.onboarding-page').evaluate((node) => node.classList.contains('is-contained-layout'))
  assert.equal(isContained, false, 'low-height landscape questionnaire should use the natural fallback')
  await assertReachableContent(page, 'low-height landscape questionnaire natural fallback', { lastQuestion: true })
  state.evidence.containedFallbackChecks.push({
    label: 'low-height landscape questionnaire natural fallback',
    viewport: shortLandscape,
    contained: isContained,
  })

  await page.setViewportSize({ width: viewports[0].width, height: viewports[0].height })
  await settleLayout(page)
  await setSidebarState(page, false)
  await page.locator('.content-area').evaluate((area) => { area.scrollTop = 0 })
  await page.locator('.questionnaire-stage-card > .el-card__body').evaluate((body) => { body.scrollTop = 0 })
}

async function pickDomainAndDirection(page) {
  const domain = page.locator('.domain-stage-card .choice-card').first()
  await domain.click()
  assert.equal(await domain.getAttribute('aria-pressed'), 'true', 'selected domain should expose aria-pressed')
  assert.ok(await domain.evaluate((node) => node.classList.contains('selected')), 'selected domain should expose selected state')
  await page.getByRole('button', { name: '下一步' }).click()
  await page.locator('.track-stage-card').waitFor()
  await assertStageFocus(page, '.track-stage-card', 'domain to track')
  const unavailable = page.locator('.track-stage-card .choice-card[disabled]')
  assert.equal(await unavailable.count(), 1, 'fixture includes one unavailable learning direction')
  assert.ok(await unavailable.evaluate((node) => node.classList.contains('unavailable')), 'unavailable direction should remain visibly disabled')
  const direction = page.locator('.track-stage-card .choice-card').filter({ hasText: '临床数据分析与质量控制' }).first()
  await direction.click()
  assert.equal(await direction.getAttribute('aria-pressed'), 'true', 'selected direction should expose aria-pressed')
  await page.getByRole('button', { name: '下一步' }).click()
  await page.locator('.questionnaire-stage-card').waitFor()
  await assertStageFocus(page, '.questionnaire-stage-card', 'track to questionnaire')
}

async function fillQuestionnaire(page, { custom = true, checkFocus = false } = {}) {
  const experience = page.locator('.question-block[data-question-id="q-experience"]')
  const conditional = page.locator('.question-block[data-question-id="q-project-detail"]')
  assert.equal(await conditional.isVisible(), false, 'conditional question should start hidden')
  const experienceSelect = experience.locator('.el-select')
  if (checkFocus) {
    await assertElementPlusFieldFocus(page, 'onboarding-questionnaire-experience-select', experienceSelect.locator('input'), experienceSelect.locator('.el-select__wrapper'))
    await chooseQuestionOptionWithKeyboard(page, experienceSelect, '有项目经验', '有项目经验，正在处理复杂医疗数据')
  } else {
    await experienceSelect.click()
    await page.getByRole('option', { name: '有项目经验，正在处理复杂医疗数据' }).click()
  }
  assert.equal(await conditional.isVisible(), true, 'conditional question should appear for matching answer')

  const goals = page.locator('.question-block[data-question-id="q-goals"]')
  await goals.getByText('案例拆解与复现', { exact: true }).click()
  await goals.getByText('数据质量控制', { exact: true }).click()

  const customBlock = page.locator('.question-block[data-question-id="q-custom"]')
  const customSelect = customBlock.locator('.el-select')
  const customInput = customSelect.locator('input').first()
  await customSelect.click()
  if (checkFocus) {
    await assertElementPlusFieldFocus(page, 'onboarding-questionnaire-custom-select', customInput, customSelect.locator('.el-select__wrapper'))
    await customSelect.click()
  }
  if (custom) {
    await customInput.fill('自定义跨中心研究场景')
    await customInput.press('Enter')
  } else {
    await page.getByRole('option', { name: '临床研究' }).click()
  }

  const background = page.locator('.question-block[data-question-id="q-background"] input').first()
  if (checkFocus) await assertElementPlusFieldFocus(page, 'onboarding-questionnaire-background-text', background, page.locator('.question-block[data-question-id="q-background"] .el-input__wrapper'))
  await background.fill('正在整理三个研究中心的临床数据，关注单位转换、缺失模式与分析留痕。')
  await conditional.locator('textarea, input').first().fill('不同中心对同一检验指标使用了不同单位，计划先确认原始来源并记录转换规则。')
  const prioritySelect = page.locator('.question-block[data-question-id="q-priority"] .el-select')
  if (checkFocus) await assertElementPlusFieldFocus(page, 'onboarding-questionnaire-priority-select', prioritySelect.locator('input'), prioritySelect.locator('.el-select__wrapper'))
  await prioritySelect.click()
  await page.getByRole('option', { name: '先建立数据校验与审计流程' }).click()
  await page.locator('.question-block[data-question-id="q-team"]').getByText('临床研究者', { exact: true }).click()
  await page.locator('.question-block[data-question-id="q-final-context"] textarea, .question-block[data-question-id="q-final-context"] input').first()
    .fill('希望结论能被团队复核，也便于在后续项目中复用。')
}

async function submitWithLoading(page, button, expectedApiPath, label) {
  const requestPromise = page.waitForRequest((request) => request.url().includes(expectedApiPath) && request.method() === 'POST')
  await button.click({ noWaitAfter: true })
  await requestPromise
  await page.waitForFunction((selector) => {
    const node = document.querySelector(selector)
    return node && (node.classList.contains('is-loading') || node.getAttribute('aria-busy') === 'true' || node.disabled)
  }, await button.evaluate((node) => {
    if (node.id) return '#' + CSS.escape(node.id)
    if (node.classList.contains('el-button--primary')) return '.action-row .el-button--primary'
    return null
  })).catch(() => {})
  const loading = await button.evaluate((node) => ({
    classLoading: node.classList.contains('is-loading'),
    ariaBusy: node.getAttribute('aria-busy'),
    disabled: node.disabled,
    text: node.innerText.trim(),
  }))
  state.evidence.loadingErrorChecks.push({ label, loading })
  assert.ok(loading.classLoading || loading.ariaBusy === 'true' || loading.disabled, label + ': submit action did not expose a loading/busy state')
}

async function assertToast(page, text) {
  const toast = page.locator('.el-message--error, .el-message').filter({ hasText: text }).last()
  await toast.waitFor({ state: 'visible' })
}

async function reachReview(page, { skipQuestions = false } = {}) {
  await pickDomainAndDirection(page)
  if (!skipQuestions) await fillQuestionnaire(page)
  await page.getByRole('button', { name: '提交问卷' }).click()
  await page.locator(skipQuestions ? '.review-stage-card' : '.diagnosis-stage-card').waitFor()
  await assertStageFocus(page, skipQuestions ? '.review-stage-card' : '.diagnosis-stage-card', 'questionnaire submit stage change')
  if (skipQuestions) return
  await page.locator('.diagnostic-item').first().waitFor()
  await page.getByRole('button', { name: '提交诊断' }).click()
  await page.locator('.review-stage-card').waitFor()
  await assertStageFocus(page, '.review-stage-card', 'diagnosis submit stage change')
}

async function focusVisibleCheck(page, label) {
  const firstCard = page.locator('.domain-stage-card .choice-card').first()
  await firstCard.focus()
  await page.keyboard.press('Tab')
  const focus = await page.evaluate(() => {
    const node = document.activeElement
    const style = getComputedStyle(node)
    return {
      tagName: node?.tagName || '',
      className: typeof node?.className === 'string' ? node.className : '',
      visible: Boolean(node?.matches(':focus-visible')),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineColor: style.outlineColor,
      boxShadow: style.boxShadow,
    }
  })
  assert.equal(focus.visible, true, label + ': keyboard navigation should expose :focus-visible')
  assert.ok(
    (focus.outlineStyle !== 'none' && Number.parseFloat(focus.outlineWidth) > 0)
      || (focus.boxShadow !== 'none' && !focus.boxShadow.includes('rgba(0, 0, 0, 0)')),
    label + ': keyboard focus has no visible outline or shadow',
  )
  state.evidence.focusChecks.push({ label, ...focus })
}

async function assertElementPlusFieldFocus(page, label, control, focusShell, { singleBorderControl = false, screenshotName = null } = {}) {
  const baseline = await focusShell.evaluate((node) => {
    const style = getComputedStyle(node)
    return { borderColor: style.borderTopColor, borderWidth: style.borderTopWidth, boxShadow: style.boxShadow }
  })
  await control.click()
  await page.waitForTimeout(240)
  const shellHandle = await focusShell.elementHandle()
  const controlHandle = await control.elementHandle()
  const focused = await page.evaluate(({ shell, control }) => {
    const outer = getComputedStyle(shell)
    const inner = getComputedStyle(control)
    return {
      active: document.activeElement === control,
      focusWithin: shell.matches(':focus-within'),
      hovered: shell.matches(':hover'),
      shell: { outlineStyle: outer.outlineStyle, outlineWidth: outer.outlineWidth, borderColor: outer.borderTopColor, borderWidth: outer.borderTopWidth, boxShadow: outer.boxShadow },
      control: { outlineStyle: inner.outlineStyle, outlineWidth: inner.outlineWidth,
        borderWidths: ['Top', 'Right', 'Bottom', 'Left'].map((side) => Number.parseFloat(inner['border' + side + 'Width']) || 0) },
    }
  }, { shell: shellHandle, control: controlHandle })
  if (screenshotName) await recordScreenshot(page, screenshotName)
  state.evidence.focusChecks.push({ label, baseline, focused })
  const details = JSON.stringify({ baseline, focused })
  assert.equal(focused.active, true, label + ': click should focus the actual control: ' + details)
  assert.equal(focused.focusWithin, true, label + ': wrapper should retain focus-within: ' + details)
  assert.equal(focused.hovered, true, label + ': focus sample should retain hover: ' + details)
  assert.ok(focused.control.outlineStyle === 'none' || Number.parseFloat(focused.control.outlineWidth) === 0,
    label + ': inner control should not draw a duplicate outline: ' + details)
  assert.ok(focused.shell.outlineStyle === 'none' || Number.parseFloat(focused.shell.outlineWidth) === 0,
    label + ': wrapper should use one focus treatment: ' + details)
  if (!singleBorderControl) assert.ok(focused.control.borderWidths.every((width) => width <= 0.5),
    label + ': inner input should not draw a separate border: ' + details)
  const shadowVisible = focused.shell.boxShadow !== 'none'
    && focused.shell.boxShadow !== baseline.boxShadow
    && !/rgba\([^)]*,\s*0(?:\.0+)?\)/i.test(focused.shell.boxShadow)
  const borderVisible = focused.shell.borderColor !== baseline.borderColor && Number.parseFloat(focused.shell.borderWidth) > 0
  assert.ok(shadowVisible || borderVisible,
    label + ': wrapper focus border or shadow should remain visible while hovered: ' + details)
  await page.keyboard.press('Escape')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Shift+Tab')
  const keyboard = await page.evaluate(({ shell, control }) => ({
    active: document.activeElement === control,
    focusVisible: document.activeElement?.matches(':focus-visible') || false,
    focusWithin: shell.matches(':focus-within'),
  }), { shell: shellHandle, control: controlHandle })
  assert.equal(keyboard.active, true, label + ': keyboard navigation should return focus to the field: ' + JSON.stringify(keyboard))
  assert.equal(keyboard.focusVisible, true, label + ': keyboard focus should remain visible: ' + JSON.stringify(keyboard))
  state.evidence.focusChecks.push({ label: label + '-keyboard', ...keyboard })
}

async function chooseQuestionOptionWithKeyboard(page, select, searchText, expectedText) {
  const input = select.locator('input').first()
  await input.click()
  await input.fill(searchText)
  await input.press('ArrowDown')
  await input.press('Enter')
  const text = await select.innerText()
  assert.ok(text.includes(expectedText), 'questionnaire select should remain keyboard-operable: ' + text)
  state.evidence.questionnaireChecks.push({ keyboardSelection: true, expectedText, selectedText: text })
}

async function contrastChecks(page, label) {
  const selectors = [
    '.domain-stage-card .card-title',
    '.domain-stage-card .card-subtitle',
    '.domain-stage-card .choice-title',
    '.domain-stage-card .choice-description',
    '.action-row .el-button--primary',
  ]
  const results = await page.evaluate((targetSelectors) => {
    const parse = (value) => {
      const raw = String(value).trim()
      const hex = raw.match(/^#([\da-f]{3,8})$/i)
      if (hex) {
        const digits = hex[1]
        const expanded = digits.length <= 4 ? [...digits].map((char) => char + char).join('') : digits
        return [parseInt(expanded.slice(0, 2), 16), parseInt(expanded.slice(2, 4), 16), parseInt(expanded.slice(4, 6), 16), expanded.length >= 8 ? parseInt(expanded.slice(6, 8), 16) / 255 : 1]
      }
      const match = raw.match(/^rgba?\((.*)\)$/i)
      if (!match) throw new Error('Unsupported computed color: ' + raw)
      const parts = match[1].replace('/', ',').split(/[\s,]+/).filter(Boolean)
      const channel = (item) => item.endsWith('%') ? Number.parseFloat(item) * 2.55 : Number.parseFloat(item)
      const alpha = parts[3] ? (parts[3].endsWith('%') ? Number.parseFloat(parts[3]) / 100 : Number.parseFloat(parts[3])) : 1
      return [channel(parts[0]), channel(parts[1]), channel(parts[2]), alpha]
    }
    const over = (top, bottom) => [
      top[0] * top[3] + bottom[0] * (1 - top[3]),
      top[1] * top[3] + bottom[1] * (1 - top[3]),
      top[2] * top[3] + bottom[2] * (1 - top[3]),
      1,
    ]
    const luminance = (color) => {
      const channels = color.slice(0, 3).map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    const extractImageColors = (image) => {
      if (image === 'none') return []
      const colors = [...image.matchAll(/rgba?\([^)]*\)|#[\da-f]{3,8}/gi)].map((match) => parse(match[0]))
      if (!colors.length || /url\(/i.test(image)) throw new Error('Cannot sample composed background image: ' + image)
      return colors
    }
    return targetSelectors.flatMap((selector) => {
      const nodes = [...document.querySelectorAll(selector)].filter((node) => node.getClientRects().length > 0)
      if (!nodes.length) return [{ selector, missing: true }]
      return nodes.map((node, index) => {
        const ancestors = []
        for (let current = node; current instanceof Element; current = current.parentElement) ancestors.push(current)
        let backgrounds = [[255, 255, 255, 1]]
        for (const current of ancestors.reverse()) {
          const style = getComputedStyle(current)
          if (Number.parseFloat(style.opacity) < 0.999 || style.mixBlendMode !== 'normal') {
            throw new Error('Cannot reliably compose opacity/blend at ' + current.className)
          }
          const color = parse(style.backgroundColor)
          const stops = extractImageColors(style.backgroundImage)
          backgrounds = backgrounds.flatMap((previous) => {
            const base = over(color, previous)
            return stops.length ? stops.map((stop) => over(stop, base)) : [base]
          })
        }
        const foreground = parse(getComputedStyle(node).color)
        const ratios = backgrounds.map((background) => ratio(luminance(over(foreground, background)), luminance(background)))
        const foregroundLum = luminance(foreground)
        const backgroundLums = backgrounds.map(luminance)
        if (foregroundLum >= Math.min(...backgroundLums) && foregroundLum <= Math.max(...backgroundLums)) ratios.push(1)
        return {
          selector: nodes.length > 1 ? selector + '[' + index + ']' : selector,
          text: node.textContent.trim(),
          color: getComputedStyle(node).color,
          composedBackgroundSamples: backgrounds.map((item) => item.slice(0, 3).map(Math.round)),
          contrast: Number(Math.min(...ratios).toFixed(2)),
        }
      })
    })
  }, selectors)
  for (const result of results) {
    assert.notEqual(result.missing, true, label + ': contrast target is missing: ' + result.selector)
    assert.ok(result.text, label + ': contrast target has no text: ' + result.selector)
    assert.ok(result.contrast >= 4.5, label + ': ' + result.selector + ' contrast ' + result.contrast + ' below 4.5:1')
  }
  state.evidence.contrastChecks.push({ label, results })
}

async function reducedMotionCheck(browser, base) {
  const page = await createPage(browser, base, 'primary', viewports[4])
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const result = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('.onboarding-page, .progress-card, .choice-card, .question-block, .action-row .el-button')]
    const durations = nodes.flatMap((node) => {
      const style = getComputedStyle(node)
      return [style.transitionDuration, style.animationDuration].flatMap((value) => value.split(',').map((part) => {
        const text = part.trim()
        return text.endsWith('ms') ? Number.parseFloat(text) / 1000 : Number.parseFloat(text)
      }))
    })
    const activeAnimations = document.querySelector('.onboarding-page')?.getAnimations({ subtree: true })
      .filter((animation) => animation.playState === 'running').length || 0
    return { maxDeclaredDurationSeconds: Math.max(0, ...durations), activeAnimations }
  })
  assert.ok(result.maxDeclaredDurationSeconds <= 0.001, 'reduced motion should remove onboarding transition/animation duration: ' + JSON.stringify(result))
  assert.equal(result.activeAnimations, 0, 'reduced motion should leave no running onboarding animations')
  state.evidence.reducedMotionChecks.push(result)
  await page.close()
}

async function saveSummary() {
  state.evidence.api.requests = state.requests
  state.evidence.api.writes = state.writes
  state.evidence.api.unexpected = state.unexpectedApi
  state.evidence.browserErrors = state.pageErrors.map((item) => ({ type: 'pageerror', ...item }))
  state.evidence.externalRequestCount = state.externalRequests.length
  state.evidence.externalRequests = state.externalRequests
  state.evidence.consoleErrors = state.consoleErrors
  state.evidence.fixtureErrors = state.failures
  state.evidence.status = state.failures.length || state.evidence.failures.length ? 'FAIL' : 'PASS'
  writeFileSync(summaryPath, JSON.stringify(state.evidence, null, 2) + '\n', 'utf8')
}

test('onboarding five-stage UI and API contract use an isolated browser fixture', { timeout: 240000 }, async () => {
  const server = makeServer()
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const base = 'http://127.0.0.1:' + address.port
  let browser
  let error = null
  try {
    browser = await chromium.launch(browserOptions('ONBOARDING_BROWSER_CHANNEL'))
    const viewportPage = await createPage(browser, base, 'primary', viewports[0])
    const domainGrid = await viewportPage.evaluate(() => {
      const grid = document.querySelector('.domain-grid')
      const cards = [...grid.querySelectorAll('.choice-card')]
      return {
        cardCount: cards.length,
        columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
        firstRowTop: cards[0]?.getBoundingClientRect().top,
        secondCardTop: cards[1]?.getBoundingClientRect().top,
        secondRowTop: cards[2]?.getBoundingClientRect().top,
        firstCardLeft: cards[0]?.getBoundingClientRect().left,
        secondCardLeft: cards[1]?.getBoundingClientRect().left,
      }
    })
    assert.equal(domainGrid.cardCount, 4, 'domain fixture should provide the actual four-card density')
    assert.equal(domainGrid.columns, 2, 'desktop domain chooser should render as a two-column selection grid')
    assert.equal(domainGrid.firstRowTop, domainGrid.secondCardTop, 'first domain row should align')
    assert.ok(domainGrid.secondRowTop > domainGrid.firstRowTop, 'four domains should occupy two visible rows')
    assert.ok(domainGrid.secondCardLeft > domainGrid.firstCardLeft, 'second domain should occupy the adjacent column')
    state.evidence.viewportChecks.push({ label: 'desktop four-domain 2x2 density', ...domainGrid })
    await verifyFitMatrix(viewportPage)
    for (const viewport of viewports) {
      await viewportPage.setViewportSize({ width: viewport.width, height: viewport.height })
      await settle(viewportPage)
      await assertLayout(viewportPage, viewport, 'domain stage ' + viewport.name)
    }
    await viewportPage.setViewportSize({ width: viewports[0].width, height: viewports[0].height })
    await focusVisibleCheck(viewportPage, 'domain stage keyboard focus')
    await contrastChecks(viewportPage, 'domain stage composed text contrast')
    await recordScreenshot(viewportPage, '01-domain-desktop-1393x871')
    await viewportPage.evaluate(() => document.activeElement?.blur?.())
    await recordScreenshot(viewportPage, 'preview-domain-desktop-1393x871')
    await viewportPage.close()

    const manyDomainPage = await createPage(browser, base, 'many-domains', fitViewports[0])
    await manyDomainPage.locator('.domain-grid .choice-card').nth(9).waitFor()
    await settleLayout(manyDomainPage)
    await assertLayout(manyDomainPage, fitViewports[0], 'ten long domains desktop fallback')
    await recordScreenshot(manyDomainPage, 'fallback-10-domains-desktop-top')
    await assertNaturalStageScroll(manyDomainPage, '.domain-stage-card', '.domain-grid .choice-card:last-child', 'ten long domains desktop fallback')
    await recordScreenshot(manyDomainPage, 'fallback-10-domains-desktop-bottom')
    await manyDomainPage.setViewportSize({ width: viewports[4].width, height: viewports[4].height })
    await settleLayout(manyDomainPage)
    await assertLayout(manyDomainPage, viewports[4], 'ten long domains mobile fallback')
    await assertNaturalStageScroll(manyDomainPage, '.domain-stage-card', '.domain-grid .choice-card:last-child', 'ten long domains mobile fallback')
    await recordScreenshot(manyDomainPage, 'fallback-10-domains-mobile-bottom')
    await manyDomainPage.close()

    const longTrackPage = await createPage(browser, base, 'long-directions', fitViewports[2])
    await longTrackPage.locator('.domain-stage-card .choice-card').first().click()
    await longTrackPage.getByRole('button', { name: '下一步' }).click()
    await assertStageFocus(longTrackPage, '.track-stage-card', 'long direction domain to track')
    assert.equal(await longTrackPage.locator('.track-stage-card .choice-card').count(), 4, 'long-direction fixture should cover the four-choice density boundary')
    await settleLayout(longTrackPage)
    await assertLayout(longTrackPage, fitViewports[2], 'four long directions short desktop fallback')
    await assertNaturalStageScroll(longTrackPage, '.track-stage-card', '.track-grid .choice-card:last-child', 'four long directions short desktop fallback')
    await longTrackPage.setViewportSize({ width: viewports[5].width, height: viewports[5].height })
    await settleLayout(longTrackPage)
    await assertLayout(longTrackPage, viewports[5], 'four long directions mobile fallback')
    await assertNaturalStageScroll(longTrackPage, '.track-stage-card', '.track-grid .choice-card:last-child', 'four long directions mobile fallback')
    await recordScreenshot(longTrackPage, 'fallback-long-directions-mobile-bottom')
    await longTrackPage.close()

    const page = await createPage(browser, base, 'primary', viewports[0])
    await page.locator('.progress-card').nth(0).waitFor()
    assert.equal(await page.locator('.progress-card').count(), 5, 'five-step progress path should render')
    assert.ok(await page.locator('.progress-card.active').count() === 1, 'exactly one step should be active')
    assert.equal(await page.locator('.progress-card.active').getAttribute('aria-current'), 'step', 'active step should expose aria-current')
    assert.ok(await page.locator('.progress-card').nth(2).isDisabled(), 'future questionnaire step should be disabled before direction choice')
    await page.locator('.domain-stage-card .choice-card').first().click()
    await page.getByRole('button', { name: '下一步' }).click()
    await page.locator('.track-stage-card').waitFor()
    await assertStageFocus(page, '.track-stage-card', 'primary domain to track')
    assert.ok(await page.locator('.progress-card').nth(0).evaluate((node) => node.classList.contains('done')), 'completed domain step should be marked complete')
    assert.equal(await page.locator('.progress-card.active').getAttribute('aria-current'), 'step')
    assert.ok(!(await page.locator('.progress-card').nth(1).isDisabled()), 'track step should become reachable after choosing a domain')
    assert.ok(await page.locator('.progress-card').nth(2).isDisabled(), 'questionnaire should remain unavailable until choosing a direction')
    await assertLayout(page, viewports[0], 'track stage desktop')
    await recordScreenshot(page, '02-direction-desktop-1393x871')
    const unavailable = page.locator('.track-stage-card .choice-card[disabled]')
    assert.equal(await unavailable.count(), 1, 'unavailable direction must remain non-selectable')
    const direction = page.locator('.track-stage-card .choice-card').filter({ hasText: '临床数据分析与质量控制' }).first()
    await direction.click()
    assert.equal(await direction.getAttribute('aria-pressed'), 'true')
    await page.getByRole('button', { name: '下一步' }).click()
    await page.locator('.questionnaire-stage-card').waitFor()
    await assertStageFocus(page, '.questionnaire-stage-card', 'primary track to questionnaire')
    await assertLayout(page, viewports[0], 'questionnaire stage desktop')
    await verifyContainedQuestionnaireMatrix(page)
    await assertLayout(page, viewports[0], 'questionnaire stage desktop after contained matrix')
    await recordScreenshot(page, '03-questionnaire-desktop-1393x871')

    await page.setViewportSize({ width: viewports[5].width, height: viewports[5].height })
    await settle(page)
    await assertLayout(page, viewports[5], 'questionnaire stage mobile-375x667')
    await assertOptionWrap(
      page,
      '.question-block[data-question-id="q-goals"] .el-checkbox__label',
      '在多中心、长周期临床数据中发现字段口径差异并形成可追溯的质量复核流程',
      'long questionnaire checkbox label on mobile',
    )
    await recordScreenshot(page, '03-questionnaire-mobile-375x667-top')
    await assertReachableContent(page, 'narrow questionnaire reaches final question and action', { lastQuestion: true })
    await recordScreenshot(page, '03-questionnaire-mobile-375x667-bottom')
    await fillQuestionnaire(page, { checkFocus: true })
    const qExperienceBlock = page.locator('.question-block[data-question-id="q-experience"]')
    assert.ok(await qExperienceBlock.getByText('有项目经验，正在处理复杂医疗数据').isVisible(), 'option label should render for its distinct submitted value')
    state.evidence.questionnaireChecks.push({
      questionCount: await page.locator('.question-block:visible').count(),
      conditionalVisible: await page.locator('.question-block[data-question-id="q-project-detail"]').isVisible(),
      optionLabel: '有项目经验，正在处理复杂医疗数据',
      expectedSubmittedValue: 'project-experience',
      customOption: '自定义跨中心研究场景',
    })
    const persistedBackground = await page.locator('.question-block[data-question-id="q-background"] input, .question-block[data-question-id="q-background"] textarea').first().inputValue()
    await page.setViewportSize({ width: fitViewports[0].width, height: fitViewports[0].height })
    await page.locator('.progress-card').nth(0).click()
    await assertStageFocus(page, '.domain-stage-card', 'questionnaire to domain restores fit')
    await fitLayoutSnapshot(page, '.domain-stage-card', 'questionnaire to domain restores fit at desktop')
    await page.locator('.progress-card').nth(2).click()
    await assertStageFocus(page, '.questionnaire-stage-card', 'domain to questionnaire preserves answers')
    assert.equal(await page.locator('.question-block[data-question-id="q-background"] input, .question-block[data-question-id="q-background"] textarea').first().inputValue(), persistedBackground, 'step navigation must preserve questionnaire answers')
    assert.equal(await page.locator('.question-block[data-question-id="q-project-detail"]').isVisible(), true, 'conditional question state should remain after returning to questionnaire')
    await page.setViewportSize({ width: viewports[0].width, height: viewports[0].height })
    await settle(page)
    await page.locator('.content-area').evaluate((node) => { node.scrollTop = 0 })
    await submitWithLoading(page, page.getByRole('button', { name: '提交问卷' }), '/api/onboarding/initial-profile', 'initial profile submit')
    await page.locator('.diagnosis-stage-card').waitFor()
    await assertStageFocus(page, '.diagnosis-stage-card', 'questionnaire submit to diagnosis')
    await assertLayout(page, viewports[0], 'diagnosis stage desktop')
    await assertContainedFormScroll(page, '.diagnosis-stage-card', 'desktop diagnosis contained scroll', { exerciseWheel: true })
    await recordScreenshot(page, '04-diagnosis-desktop-1393x871')
    assert.equal(await page.locator('.diagnostic-item').count(), 3, 'diagnosis stage should render single, multiple and text fixtures')
    assert.deepEqual(await page.locator('.diagnostic-item').evaluateAll((items) => items.map((item) => item.dataset.questionId)), ['diag-single', 'diag-multiple', 'diag-text'])
    await page.setViewportSize({ width: viewports[5].width, height: viewports[5].height })
    await settle(page)
    await assertLayout(page, viewports[5], 'diagnosis stage mobile-375x667')
    await assertReachableContent(page, 'mobile diagnosis reaches final item and action')
    await assertOptionWrap(
      page,
      '.diagnostic-item[data-question-id="diag-single"] .el-radio__label',
      '按统一字段字典逐一核查多个研究中心的原始来源和单位转换规则',
      'long diagnosis radio label on mobile',
    )
    await page.setViewportSize({ width: viewports[0].width, height: viewports[0].height })
    await settle(page)
    await page.locator('.content-area').evaluate((node) => { node.scrollTop = 0 })
    await page.locator('.diagnostic-item[data-question-id="diag-single"]').getByText('按统一字段字典逐一核查多个研究中心的原始来源和单位转换规则', { exact: true }).click()
    await page.locator('.diagnostic-item[data-question-id="diag-multiple"]').getByText('关键字段缺失', { exact: true }).click()
    await page.locator('.diagnostic-item[data-question-id="diag-multiple"]').getByText('字段单位不一致', { exact: true }).click()
    await page.locator('.diagnostic-item[data-question-id="diag-text"] textarea').fill('记录字段、来源、转换规则、决策人和影响范围。')
    await submitWithLoading(page, page.getByRole('button', { name: '提交诊断' }), '/api/diagnosis/submit', 'first diagnostic submit')
    await page.locator('.diagnostic-item[data-question-id="diag-retest"]').waitFor()
    assert.ok(await page.locator('.diagnosis-stage-card').getByText('复测：发现单位口径不一致后', { exact: false }).isVisible(), 'retest branch should keep the learner in diagnosis')
    await page.locator('.diagnostic-item[data-question-id="diag-retest"] .el-radio').first().click()
    await page.getByRole('button', { name: '提交诊断' }).click()
    await page.locator('.review-stage-card').waitFor()
    await assertStageFocus(page, '.review-stage-card', 'diagnosis submit to review')
    await page.getByText('多中心数据口径核对', { exact: false }).waitFor()
    await assertLayout(page, viewports[0], 'review stage desktop')
    await assertContainedFormScroll(page, '.review-stage-card', 'desktop resource review contained scroll')
    await recordScreenshot(page, '05-review-desktop-1393x871')
    assert.equal(await page.locator('.resource-type-grid .el-checkbox').count(), 5, 'review should expose all five resource types')
    const selectedDefaults = await page.locator('.resource-type-grid .el-checkbox.is-checked .resource-option strong').allTextContents()
    assert.deepEqual(selectedDefaults.map((item) => item.trim()), defaultResourceTypes, 'default selected resource types should stay unchanged')
    for (const item of ['复习清单', '案例分析']) await page.locator('.resource-type-grid').getByText(item, { exact: true }).click()

    await page.setViewportSize({ width: viewports[5].width, height: viewports[5].height })
    await settle(page)
    await assertLayout(page, viewports[5], 'review stage mobile-375x667')
    await recordScreenshot(page, '05-review-mobile-375x667-top')
    await assertReachableContent(page, 'narrow review reaches primary action')
    await recordScreenshot(page, '05-review-mobile-375x667-bottom')
    await page.locator('.resource-selection-form textarea').fill('请优先解释数据质量判断依据，并提供可复核的多中心案例。  ')
    const payloadBeforeGeneration = state.writes.length
    const generateButton = page.getByRole('button', { name: '生成并进入状态页' })
    await submitWithLoading(page, generateButton, '/api/generate/jobs', 'generation submit with Claim disabled')
    await page.waitForURL((url) => url.pathname === '/generate')
    const primaryWrites = state.writes.slice(payloadBeforeGeneration)
    assert.equal(primaryWrites.filter((item) => item.path === '/api/generate/jobs').length, 1, 'Claim disabled should submit one generation request for all selected types')
    assert.deepEqual(primaryWrites[0].body.resource_types, resourceTypes)
    assert.equal(primaryWrites[0].body.include_claim_check, false)
    assert.equal(primaryWrites[0].body.constraints.supplemental_requirements, '请优先解释数据质量判断依据，并提供可复核的多中心案例。')
    assert.equal(primaryWrites[0].body.learner_id, 'onboarding-fixture-user__track-main')
    assert.equal(primaryWrites[0].body.knowledge_base_id, 'track-main')
    assert.match(primaryWrites[0].body.topic, /临床数据分析与质量控制/)
    const primaryProfileWrite = state.writes.find((item) => item.scenario === 'primary' && item.path === '/api/onboarding/initial-profile')
    assert.ok(primaryProfileWrite, 'questionnaire payload should be recorded')
    assert.equal(primaryProfileWrite.body.answers['q-experience'], 'project-experience', 'submitted option should preserve its value rather than display label')
    assert.deepEqual(primaryProfileWrite.body.answers['q-goals'], ['case-study', 'data-quality'])
    assert.equal(primaryProfileWrite.body.answers['q-custom'], '自定义跨中心研究场景', 'allow-create question should submit its custom value')
    assert.match(primaryProfileWrite.body.answers['q-project-detail'], /不同中心/)
    assert.equal(primaryProfileWrite.body.answers['q-priority'], 'quality-first')
    assert.deepEqual(primaryProfileWrite.body.answers['q-team'], ['临床研究者'])
    assert.equal(primaryProfileWrite.body.answers['q-final-context'], '希望结论能被团队复核，也便于在后续项目中复用。')
    const primaryDiagnosisWrites = state.writes.filter((item) => item.scenario === 'primary' && item.path === '/api/diagnosis/submit')
    assert.equal(primaryDiagnosisWrites.length, 2, 'diagnosis retest should submit both the first round and follow-up round')
    assert.deepEqual(primaryDiagnosisWrites[0].body.answers.map((item) => item.question_id), ['diag-single', 'diag-multiple', 'diag-text'])
    assert.equal(primaryDiagnosisWrites[0].body.answers[0].answer, '按统一字段字典逐一核查多个研究中心的原始来源和单位转换规则')
    assert.deepEqual([...primaryDiagnosisWrites[0].body.answers[1].answer].sort(), ['字段单位不一致', '关键字段缺失'].sort())
    assert.equal(primaryDiagnosisWrites[0].body.answers[2].answer, '记录字段、来源、转换规则、决策人和影响范围。')
    assert.equal(primaryDiagnosisWrites[1].body.answers[0].question_id, 'diag-retest')
    assert.equal(primaryDiagnosisWrites[1].body.answers[0].answer, '确认来源并记录转换规则')
    assert.equal(new URL(page.url()).searchParams.get('learnerId'), 'onboarding-fixture-user__track-main')
    assert.ok(new URL(page.url()).searchParams.get('runId'))
    state.evidence.payloadChecks.push({ scenario: 'primary', requestCount: primaryWrites.length, request: primaryWrites[0], route: page.url() })
    state.evidence.flowChecks.push({ scenario: 'primary', stages: ['domain', 'track', 'questionnaire', 'diagnosis', 'retest', 'review', 'generate'], route: page.url() })
    await page.close()

    const noDiagnosis = await createPage(browser, base, 'no-diagnosis', viewports[0])
    await pickDomainAndDirection(noDiagnosis)
    await fillQuestionnaire(noDiagnosis, { custom: false })
    await noDiagnosis.getByRole('button', { name: '提交问卷' }).click()
    await noDiagnosis.locator('.review-stage-card').waitFor()
    await assertStageFocus(noDiagnosis, '.review-stage-card', 'questionnaire without diagnosis to review')
    assert.equal(await noDiagnosis.locator('.diagnosis-stage-card').count(), 0, 'empty diagnosis question list should skip directly to review')
    assert.equal(state.writes.filter((item) => item.scenario === 'no-diagnosis' && item.path === '/api/diagnosis/submit').length, 0)
    await assertLayout(noDiagnosis, viewports[0], 'review after no diagnostic questions')
    state.evidence.flowChecks.push({ scenario: 'no-diagnosis', stages: ['domain', 'track', 'questionnaire', 'review'], diagnosisWrites: 0 })
    await noDiagnosis.close()

    const claimPage = await createPage(browser, base, 'claim-split', viewports[1])
    await reachReview(claimPage)
    assert.equal(await claimPage.locator('.resource-type-grid .el-checkbox').count(), 5)
    for (const item of ['复习清单', '案例分析']) {
      const checkbox = claimPage.locator('.resource-type-grid .el-checkbox').filter({ hasText: item })
      if (!(await checkbox.evaluate((node) => node.classList.contains('is-checked')))) await checkbox.click()
    }
    const claimSwitch = claimPage.locator('.claim-review-control .el-switch')
    await claimSwitch.click()
    assert.equal(await claimSwitch.locator('input[role="switch"]').getAttribute('aria-checked'), 'true', 'Claim switch should expose enabled state')
    const claimWriteStart = state.writes.length
    await claimPage.getByRole('button', { name: '生成并进入状态页' }).click()
    await claimPage.waitForURL((url) => url.pathname === '/generate')
    const claimWrites = state.writes.slice(claimWriteStart).filter((item) => item.path === '/api/generate/jobs')
    assert.equal(claimWrites.length, 5, 'Claim enabled with five types should split into one request per type')
    assert.deepEqual(claimWrites.map((item) => item.body.resource_types), resourceTypes.map((item) => [item]))
    assert.ok(claimWrites.every((item) => item.body.include_claim_check === true))
    assert.ok(claimWrites.every((item) => item.body.constraints.supplemental_requirements === ''))
    state.evidence.payloadChecks.push({ scenario: 'claim-split', requestCount: claimWrites.length, requests: claimWrites, route: claimPage.url() })
    state.evidence.flowChecks.push({ scenario: 'claim-split', stages: ['domain', 'track', 'questionnaire', 'diagnosis', 'review', 'generate'], claimRequests: claimWrites.length })
    await claimPage.close()

    const errorPage = await createPage(browser, base, 'errors', viewports[0])
    await pickDomainAndDirection(errorPage)
    await fillQuestionnaire(errorPage)
    const profileSubmit = errorPage.getByRole('button', { name: '提交问卷' })
    await profileSubmit.click()
    await assertToast(errorPage, '验收问卷提交失败')
    assert.ok(await errorPage.locator('.questionnaire-stage-card').isVisible(), 'failed questionnaire request should keep the current stage')
    await profileSubmit.click()
    await errorPage.locator('.diagnosis-stage-card').waitFor()
    await assertStageFocus(errorPage, '.diagnosis-stage-card', 'profile retry to diagnosis')
    const diagnosisSubmit = errorPage.getByRole('button', { name: '提交诊断' })
    await diagnosisSubmit.click()
    await assertToast(errorPage, '验收诊断暂不可用')
    assert.ok(await errorPage.locator('.diagnosis-stage-card').isVisible(), 'failed diagnostic request should keep the current stage')
    await diagnosisSubmit.click()
    await errorPage.locator('.review-stage-card').waitFor()
    await assertStageFocus(errorPage, '.review-stage-card', 'diagnosis retry to review')
    const generationSubmit = errorPage.getByRole('button', { name: '生成并进入状态页' })
    await generationSubmit.click()
    await assertToast(errorPage, '验收生成服务暂不可用')
    assert.ok(await errorPage.locator('.review-stage-card').isVisible(), 'failed generation request should keep resource review available')
    await generationSubmit.click()
    await errorPage.waitForURL((url) => url.pathname === '/generate')
    const errorWrites = state.writes.filter((item) => item.scenario === 'errors')
    assert.equal(errorWrites.filter((item) => item.path === '/api/onboarding/initial-profile').length, 2)
    assert.equal(errorWrites.filter((item) => item.path === '/api/diagnosis/submit').length, 2)
    assert.equal(errorWrites.filter((item) => item.path === '/api/generate/jobs').length, 2)
    state.evidence.loadingErrorChecks.push({
      scenario: 'errors',
      retryCounts: {
        profile: errorWrites.filter((item) => item.path === '/api/onboarding/initial-profile').length,
        diagnosis: errorWrites.filter((item) => item.path === '/api/diagnosis/submit').length,
        generation: errorWrites.filter((item) => item.path === '/api/generate/jobs').length,
      },
      feedback: ['问卷提交失败', '诊断提交失败', '生成任务提交失败'],
    })
    await errorPage.close()

    await reducedMotionCheck(browser, base)
    assert.deepEqual(state.unexpectedApi, [], 'all fixture API calls should match known read/write contracts')
    assert.deepEqual(state.externalRequests, [], 'browser must not contact a live backend, dev server or external service')
    assert.deepEqual(state.pageErrors, [], 'browser should have no uncaught page exceptions')
    assert.deepEqual(state.failures, [], 'fixture server should have no internal errors')
    const expectedWritePaths = new Set(['/api/onboarding/initial-profile', '/api/diagnosis/submit', '/api/generate/jobs'])
    assert.ok(state.writes.every((item) => expectedWritePaths.has(item.path)), 'only intended onboarding and generation fixture writes are allowed')
    assert.ok(state.evidence.screenshots.length >= 7, 'five desktop stages and narrow questionnaire/review screenshots should be saved')
    state.evidence.status = 'PASS'
  } catch (caught) {
    error = caught
    state.evidence.status = 'FAIL'
    state.evidence.failures.push(caught?.stack || String(caught))
    throw caught
  } finally {
    await browser?.close().catch(() => {})
    await new Promise((resolve) => server.close(resolve))
    await saveSummary()
    if (error) process.stderr.write('Onboarding browser evidence: ' + summaryPath + '\n')
  }
})
