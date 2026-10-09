import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const workspaceRoot = path.resolve(root, '..')
const dist = path.join(root, 'dist')
const reportDir = path.join(root, 'tests/test-results/feature-showcase')
if (!existsSync(path.join(dist, 'index.html'))) throw new Error('Run npm --prefix frontend run build first')
mkdirSync(reportDir, { recursive: true })
const trainingMetadata = JSON.parse(readFileSync(path.join(workspaceRoot, 'knowledge_base/rag_engineering_training/metadata.json'), 'utf8'))
const metadataNodes = trainingMetadata.skill_nodes
const metadataIdByName = new Map(metadataNodes.map(node => [node.name, node.node_id]))
const metadataPrerequisiteId = value => metadataIdByName.get(value) || value
const metadataEdges = metadataNodes.flatMap(node => (node.prerequisites || []).map(prerequisite => ({ from: metadataPrerequisiteId(prerequisite), to: node.node_id })))

const features = [
  { id: 'multi-agent', legacyPath: '/features/multi-agent', key: 'agents', title: '协作星图', delay: 1800 },
  { id: 'evidence', legacyPath: '/features/evidence', key: 'evidence', title: '证据档案' },
  { id: 'learning-path', legacyPath: '/features/learning-path', key: 'path', title: '成长航线' },
  { id: 'feedback-loop', legacyPath: '/features/feedback-loop', key: 'feedback', title: '反馈进阶' },
]
const screenLabels = ['学习概览', '平台能力', '协作星图', '证据档案', '成长航线', '反馈进阶']
const expectedFeedbackRoutePath = 'M380 130Q380 157 350 157H210Q175 157 175 192V284H457'
const viewports = [
  { name: 'desktop', width: 1257, height: 860, scale: 1.5 },
  { name: 'wide', width: 1440, height: 900, scale: 1 },
  { name: 'compact', width: 1024, height: 768, scale: 1 },
  { name: 'tablet', width: 768, height: 1024, scale: 1 },
  { name: 'mobile', width: 390, height: 844, scale: 1 },
  { name: 'narrow', width: 375, height: 812, scale: 1 },
  { name: 'short', width: 1257, height: 520, scale: 1 },
]

const errors = []
const layoutFailures = []
const api = { requests: [], writes: [] }
const evidence = {
  status: 'RUNNING',
  browser: 'Microsoft Edge via Playwright channel msedge',
  base: null,
  viewports,
  layoutChecks: [],
  layoutFailures,
  routes: [],
  interactions: [],
  contrastChecks: [],
  focusChecks: [],
  motionChecks: [],
  screenChecks: [],
  traceLayoutChecks: [],
  themeChecks: [],
  metadataProjectionChecks: [],
  journeyCompositionChecks: [],
  feedbackRouteChecks: [],
  feedbackTimingChecks: [],
  agentGeometryChecks: [],
  feedbackLifecycleChecks: [],
  evidenceVerdictReadyWaits: [],
  evidenceTimingChecks: [],
  evidenceLifecycleChecks: [],
  sourceAlignmentChecks: [],
  feedbackPauseScrollChecks: [],
  agentTimingChecks: [],
  agentLifecycleChecks: [],
  screenshots: [],
  browserErrors: errors,
  api,
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://feature-showcase-fixture')
  const json = (value, status = 200) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
    res.end(JSON.stringify(value))
  }

  // This fixture is deliberately isolated: no API request is ever proxied to a backend.
  if (url.pathname.startsWith('/api/')) {
    const method = (req.method || 'GET').toUpperCase()
    const record = { method, path: url.pathname }
    api.requests.push(record)
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) api.writes.push(record)
    if (url.pathname === '/api/auth/me') return json({ user: null })
    return json({ items: [], resources: [], domains: [], data: [], user: null })
  }

  let requestedPath
  try {
    requestedPath = decodeURIComponent(url.pathname)
  } catch {
    res.writeHead(400)
    return res.end('Bad path')
  }
  const candidate = path.resolve(dist, `.${requestedPath}`)
  const safe = candidate === dist || candidate.startsWith(`${dist}${path.sep}`)
  const isFile = safe && existsSync(candidate) && statSync(candidate).isFile()
  const file = isFile ? candidate : path.join(dist, 'index.html')
  const mimeTypes = {
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
  }
  res.writeHead(200, { 'content-type': mimeTypes[path.extname(file).toLowerCase()] || 'application/octet-stream' })
  res.end(readFileSync(file))
})

let browser
let base
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
base = `http://127.0.0.1:${server.address().port}`
evidence.base = base

function routeUrl(feature) {
  return `${base}/#${feature.id}`
}

async function newPage(options = {}) {
  const page = await browser.newPage({ viewport: { width: 1257, height: 860 }, deviceScaleFactor: 1.5, ...options })
  page.on('pageerror', error => errors.push(error.message))
  return page
}

async function waitForVisualStability(page) {
  await page.evaluate(async () => {
    await document.fonts.ready
    const root = document.querySelector('.landing-page')
    if (!root) return

    for (let round = 0; round < 20; round++) {
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      const finiteAnimations = root.getAnimations({ subtree: true }).filter(animation => {
        if (animation.playState !== 'running' && animation.playState !== 'pending') return false
        return Number.isFinite(animation.effect?.getComputedTiming().endTime)
      })
      if (!finiteAnimations.length) return
      await Promise.all(finiteAnimations.map(animation => animation.finished.catch(() => undefined)))
    }
    throw new Error('Finite showcase animations did not settle after 20 completion rounds')
  })
}

async function waitForEvidenceVerdictReady(page, label = 'evidence route') {
  await page.waitForFunction(() => {
    const archive = document.querySelector('#evidence .evidence-archive')
    return archive?.dataset.verdictReady === 'true' && archive.dataset.phase === '3' && Number(archive.dataset.verdictProgress) >= 1
  }, null, { timeout: 15000 })
  const playback = page.locator('#evidence .trace-playback')
  if (await playback.getAttribute('aria-label') === '暂停溯源演示') await playback.click()
  await page.waitForFunction(() => {
    const archive = document.querySelector('#evidence .evidence-archive')
    return archive?.dataset.verdictReady === 'true' && archive.dataset.phase === '3' && archive.dataset.playing === 'false'
  }, null, { timeout: 1500 })
  const result = await page.evaluate(() => {
    const archive = document.querySelector('#evidence .evidence-archive')
    return {
      rule: archive?.dataset.verdict || null,
      phase: Number(archive?.dataset.phase),
      cycle: Number(archive?.dataset.cycle),
      playing: archive?.dataset.playing === 'true',
      verdictReady: archive?.dataset.verdictReady === 'true',
      verdictProgress: Number(archive?.dataset.verdictProgress),
      reached: archive?.querySelector('.trace-verdict')?.dataset.reached === 'true',
      verdict: archive?.querySelector('.trace-verdict-result strong')?.innerText.trim() || '',
      sourceState: archive?.querySelector('.trace-source')?.dataset.sourceState || null,
    }
  })
  assert.ok(result.verdictReady && result.verdictProgress >= 1 && result.phase === 3 && !result.playing && result.reached, `${label}: capture/result must wait for the natural terminal-light arrival, then explicitly pause: ${JSON.stringify(result)}`)
  evidence.evidenceVerdictReadyWaits.push({ label, ...result, explicitlyPaused: true })
  return result
}

async function waitForFeedbackAlignment(page, label) {
  try {
    await page.waitForFunction(() => {
      const scroller = document.querySelector('.landing-main')
      const target = document.querySelector('#feedback-loop')
      if (!scroller || !target) return false
      const sample = { scrollTop: scroller.scrollTop, offsetTop: target.offsetTop }
      const previous = window.__feedbackAlignmentSample
      window.__feedbackAlignmentSample = sample
      return Math.abs(sample.scrollTop - sample.offsetTop) < 2 && previous && Math.abs(previous.scrollTop - sample.scrollTop) < 0.5 && Math.abs(previous.offsetTop - sample.offsetTop) < 0.5
    }, null, { polling: 'raf', timeout: 3000 })
  } catch (error) {
    throw new Error(`${label}: feedback screen scroll position did not settle`, { cause: error })
  }
}

async function assertFeature(page, feature) {
  const url = new URL(page.url())
  assert.equal(url.pathname, '/', `${feature.id}: expected the homepage path`)
  assert.equal(url.hash, `#${feature.id}`, `${feature.id}: browser URL does not match the expected section`)
  const panel = page.locator(`#${feature.id}.showcase-panel[data-feature="${feature.key}"]`)
  await panel.waitFor({ state: 'visible' })
  assert.equal(await page.locator('.landing-screen').count(), 6, 'Homepage should expose six screens')
  assert.equal(await page.locator('.landing-main').count(), 1, 'Homepage should use one shared screen scroller')
  assert.equal(await page.locator('h1').count(), 1, 'Homepage should have a single h1')
  assert.ok((await page.locator('h1').innerText()).trim(), 'Homepage h1 is empty')
  assert.ok(await panel.locator('h2').count(), `${feature.id}: showcase panel should use h2 headings`)
  return panel
}

async function pauseFeedbackForStableRendering(page, panel) {
  const playback = panel.locator('.feedback-playback')
  await playback.waitFor({ state: 'visible' })
  await waitForFeedbackAlignment(page, 'before feedback pause')
  const before = await page.evaluate(() => {
    const scroller = document.querySelector('.landing-main')
    const target = document.querySelector('#feedback-loop')
    const active = document.activeElement
    return {
      scrollTop: scroller?.scrollTop ?? null,
      offsetTop: target?.offsetTop ?? null,
      mainTop: scroller?.getBoundingClientRect().top ?? null,
      panelTop: target?.getBoundingClientRect().top ?? null,
      activeElement: active === document.body ? 'body' : active?.id || active?.className || active?.tagName || null,
    }
  })
  if (await playback.getAttribute('aria-label') === '暂停演示') {
    await playback.evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  }
  await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.dataset.playing === 'false')
  await waitForFeedbackAlignment(page, 'after feedback pause')
  assert.equal(await playback.getAttribute('aria-label'), '继续演示', 'A deterministic feedback render should have the automatic loop paused')
  const after = await page.evaluate(() => {
    const scroller = document.querySelector('.landing-main')
    const target = document.querySelector('#feedback-loop')
    const active = document.activeElement
    return {
      scrollTop: scroller?.scrollTop ?? null,
      offsetTop: target?.offsetTop ?? null,
      mainTop: scroller?.getBoundingClientRect().top ?? null,
      panelTop: target?.getBoundingClientRect().top ?? null,
      activeElement: active === document.body ? 'body' : active?.id || active?.className || active?.tagName || null,
    }
  })
  assert.ok(Math.abs(before.scrollTop - before.offsetTop) < 2 && Math.abs(before.panelTop - before.mainTop) < 2, `Feedback should align before pausing: ${JSON.stringify(before)}`)
  assert.ok(Math.abs(after.scrollTop - after.offsetTop) < 2 && Math.abs(after.panelTop - after.mainTop) < 2, `Pausing should preserve the active screen alignment: ${JSON.stringify(after)}`)
  assert.equal(after.offsetTop, before.offsetTop, 'Pausing must not change the feedback section offset')
  assert.equal(after.activeElement, before.activeElement, 'Pausing for screenshots must not move keyboard focus')
  evidence.feedbackPauseScrollChecks.push({ viewport: page.viewportSize(), before, after, source: 'synthetic click event for screenshot/stability preparation' })
  await panel.locator('.feedback-stage[data-feedback-step="1"]').evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await waitForFeedbackAlignment(page, 'after selecting the static feedback route stage')
  const workbench = panel.locator('.feedback-workbench')
  assert.equal(await workbench.getAttribute('data-phase'), '1', 'Stable feedback screenshots should show the route rerouting turn')
  assert.equal(await workbench.getAttribute('data-playing'), 'false', 'The static screenshot should retain the visible paused state')
}

async function openFeature(page, feature, { reload = false, pauseFeedback = true } = {}) {
  await page.goto(routeUrl(feature), { waitUntil: 'networkidle' })
  if (reload) await page.reload({ waitUntil: 'networkidle' })
  const panel = await assertFeature(page, feature)
  if (feature.key === 'feedback' && pauseFeedback) await pauseFeedbackForStableRendering(page, panel)
  await waitForVisualStability(page)
  await page.waitForFunction(expected => document.querySelector('.landing-page')?.dataset.theme === expected, feature.key)
  return panel
}

async function geometry(page, feature, viewport) {
  await waitForVisualStability(page)
  const metrics = await page.evaluate(() => {
    const root = document.querySelector('.landing-page')
    const scroll = document.querySelector('.landing-main')
    const panel = document.querySelector(`${location.hash}.showcase-panel[data-feature]`)
    const main = document.querySelector('.landing-main')
    const nav = document.querySelector('.landing-nav')
    const world = panel?.querySelector('.feature-world')
    const intro = world?.querySelector('.feature-intro')
    const scene = world?.querySelector('.feature-scene')
    const cue = panel?.querySelector('.screen-cue')
    const next = panel?.nextElementSibling
    const rect = element => {
      if (!element) return null
      const box = element.getBoundingClientRect()
      return { top: box.top, bottom: box.bottom, height: box.height }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      root: root ? { width: root.clientWidth, scrollWidth: root.scrollWidth } : null,
      scroller: scroll ? { width: scroll.clientWidth, scrollWidth: scroll.scrollWidth } : null,
      panel: rect(panel), main: rect(main), nextScreen: rect(next),
      world: rect(world), intro: rect(intro), scene: rect(scene), cue: rect(cue),
      theme: root?.dataset.theme || null,
      navBackground: nav ? getComputedStyle(nav).backgroundColor : null,
      panelBackground: panel ? getComputedStyle(panel).backgroundColor : null,
      screenCount: document.querySelectorAll('.landing-screen').length,
      paged: root?.classList.contains('is-paged') || false,
    }
  })
  const violations = []
  if (metrics.documentWidth > metrics.viewport.width + 1) violations.push('document has horizontal overflow')
  if (metrics.bodyWidth > metrics.viewport.width + 1) violations.push('body has horizontal overflow')
  if (!metrics.root) violations.push('landing root missing')
  else if (metrics.root.scrollWidth > metrics.root.width + 1) violations.push('landing root has horizontal overflow')
  if (!metrics.scroller) violations.push('shared landing scroller missing')
  else if (metrics.scroller.scrollWidth > metrics.scroller.width + 1) violations.push('landing scroller has horizontal overflow')
  if (!metrics.panel) violations.push('showcase panel missing')
  else if (!metrics.main || Math.abs(metrics.panel.top - metrics.main.top) > 2) violations.push('showcase panel is not aligned to the active screen')
  if (metrics.theme !== feature.key) violations.push(`top-level theme is ${metrics.theme}, expected ${feature.key}`)
  if (metrics.navBackground !== metrics.panelBackground) violations.push('top navigation background does not follow the active showcase theme')
  if (metrics.screenCount !== 6) violations.push('homepage does not contain six screens')
  if (['desktop', 'wide', 'compact'].includes(viewport.name)) {
    if (!metrics.paged) violations.push('desktop should use full-screen paging')
    if (metrics.panel && metrics.main && Math.abs(metrics.panel.height - metrics.main.height) > 2) violations.push('active panel does not fill the screen')
    if (metrics.nextScreen && metrics.main && metrics.nextScreen.top < metrics.main.bottom - 1) violations.push('next screen is visible')
    if (metrics.world && metrics.main && (metrics.world.top < metrics.main.top - 1 || metrics.world.bottom > metrics.main.bottom + 1)) violations.push('feature content world is clipped by the active screen')
    if (metrics.intro && metrics.world && (metrics.intro.top < metrics.world.top - 1 || metrics.intro.bottom > metrics.world.bottom + 1)) violations.push('feature introduction is clipped by its content world')
    if (metrics.scene && metrics.world && (metrics.scene.top < metrics.world.top - 1 || metrics.scene.bottom > metrics.world.bottom + 1)) violations.push('feature scene is clipped by its content world')
    if (metrics.cue && metrics.main && (metrics.cue.top < metrics.main.top - 1 || metrics.cue.bottom > metrics.main.bottom + 1)) violations.push('next-screen control is clipped by the active screen')
  }
  const check = { feature: feature.key, screen: feature.id, viewport: viewport.name, ...metrics, violations }
  evidence.layoutChecks.push(check)
  evidence.screenChecks.push({ feature: feature.key, screen: feature.id, viewport: viewport.name, paged: metrics.paged, panel: metrics.panel, main: metrics.main, nextScreen: metrics.nextScreen })
  if (violations.length) layoutFailures.push(check)
}

async function verifySelectedStateFits(page, feature) {
  await geometry(page, feature, viewports[0])
}

async function assertEvidenceComposition(panel, label) {
  const metrics = await panel.evaluate(root => {
    const archive = root.querySelector('.evidence-archive')
    const trace = archive?.querySelector('.evidence-trace')
    const claim = trace?.querySelector('.trace-claim')
    const evidence = trace?.querySelector('.trace-evidence')
    const source = trace?.querySelector('.trace-source')
    const verdict = archive?.querySelector('.trace-verdict')
    const wiring = trace?.querySelector('svg.trace-wiring')
    const signal = wiring?.querySelector('.trace-signal')
    const signalLength = signal?.getTotalLength() || 0
    const verdictWiring = trace?.querySelector('svg.verdict-wiring')
    const verdictSignal = verdictWiring?.querySelector('.trace-signal')
    const connectorLabels = [...(trace?.querySelectorAll('.trace-claim-link, .trace-source-link') || [])]
    const box = element => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height }
    }
    let pathEnd = null, evidenceEnd = null
    let pathSamples = []
    if (signal && wiring && signalLength > 0) {
      const total = signalLength
      const point = wiring.createSVGPoint()
      const endpoint = signal.getPointAtLength(total)
      point.x = endpoint.x
      point.y = endpoint.y
      const screen = point.matrixTransform(wiring.getScreenCTM())
      pathEnd = { x: screen.x, y: screen.y }
      const evidencePoint = signal.getPointAtLength(total * (161 / total))
      point.x = evidencePoint.x
      point.y = evidencePoint.y
      const screenEvidence = point.matrixTransform(wiring.getScreenCTM())
      evidenceEnd = { x: screenEvidence.x, y: screenEvidence.y }
      pathSamples = Array.from({ length: 257 }, (_, index) => {
        const local = signal.getPointAtLength(total * index / 256)
        point.x = local.x
        point.y = local.y
        const transformed = point.matrixTransform(wiring.getScreenCTM())
        return { x: transformed.x, y: transformed.y }
      })
    }
    const connectorGeometry = connectorLabels.map(label => {
      const rect = label.getBoundingClientRect()
      let gap = Infinity
      for (const point of pathSamples) {
        const dx = Math.max(rect.left - point.x, 0, point.x - rect.right)
        const dy = Math.max(rect.top - point.y, 0, point.y - rect.bottom)
        gap = Math.min(gap, Math.hypot(dx, dy))
      }
      const style = getComputedStyle(label)
      return { text: label.innerText.trim(), gap, backgroundColor: style.backgroundColor, backgroundImage: style.backgroundImage }
    })
    let verdictPathStart = null, verdictPathEnd = null, verdictPathLength = 0
    if (verdictSignal && verdictWiring && verdictSignal.getTotalLength() > 0) {
      verdictPathLength = verdictSignal.getTotalLength()
      const point = verdictWiring.createSVGPoint()
      const start = verdictSignal.getPointAtLength(0)
      const end = verdictSignal.getPointAtLength(verdictPathLength)
      point.x = start.x; point.y = start.y
      const screenStart = point.matrixTransform(verdictWiring.getScreenCTM())
      point.x = end.x; point.y = end.y
      const screenEnd = point.matrixTransform(verdictWiring.getScreenCTM())
      verdictPathStart = { x: screenStart.x, y: screenStart.y }
      verdictPathEnd = { x: screenEnd.x, y: screenEnd.y }
    }
    const verdictBox = verdict?.getBoundingClientRect()
    const verdictTarget = verdictBox ? { x: verdictBox.right, y: verdictBox.top + verdictBox.height / 2 } : null
    const verdictEndpointError = verdictPathEnd && verdictTarget ? Math.hypot(verdictPathEnd.x - verdictTarget.x, verdictPathEnd.y - verdictTarget.y) : null
    const hit = verdictBox && document.elementFromPoint(verdictBox.left + verdictBox.width / 2, verdictBox.top + verdictBox.height / 2)
    return {
      viewportWidth: innerWidth,
      verdictCode: archive?.dataset.verdict || null,
      archive: box(archive), trace: box(trace), claim: box(claim), evidence: box(evidence), source: box(source), verdict: box(verdict), pathEnd, evidenceEnd,
      verdictPathStart, verdictPathEnd, verdictTarget, verdictEndpointError, verdictPathLength, connectorGeometry,
      pathCount: wiring?.querySelectorAll('path').length || 0,
      verdictPathCount: verdictWiring?.querySelectorAll('path').length || 0,
      pointerEvents: wiring ? getComputedStyle(wiring).pointerEvents : null,
      verdictPointerEvents: verdictWiring ? getComputedStyle(verdictWiring).pointerEvents : null,
      sourceTransform: source ? getComputedStyle(source).transform : null,
      sourceDecorationTransform: source ? getComputedStyle(source, '::before').transform : null,
      claimStyle: claim ? { background: getComputedStyle(claim).backgroundColor, borderWidth: getComputedStyle(claim).borderTopWidth, borderStyle: getComputedStyle(claim).borderTopStyle } : null,
      evidenceStyle: evidence ? { background: getComputedStyle(evidence).backgroundColor, borderWidth: getComputedStyle(evidence).borderTopWidth, borderStyle: getComputedStyle(evidence).borderTopStyle } : null,
      verdictHit: Boolean(verdict && hit && (hit === verdict || verdict.contains(hit))),
    }
  })
  assert.ok(metrics.archive && metrics.trace && metrics.claim && metrics.evidence && metrics.source && metrics.verdict, `${label}: evidence composition elements should be measurable`)
  assert.equal(metrics.pathCount, 2, `${label}: the Claim-to-Source route should preserve its base rail and active trace`)
  assert.equal(metrics.verdictPathCount, 2, `${label}: the independent verdict route should preserve its base rail and active trace`)
  assert.equal(metrics.pointerEvents, 'none', `${label}: decorative evidence wiring must not intercept controls`)
  assert.equal(metrics.verdictPointerEvents, 'none', `${label}: decorative verdict wiring must not intercept controls`)
  assert.equal(metrics.sourceTransform, 'none', `${label}: source document should be square and unrotated`)
  const decorationMatrix = metrics.sourceDecorationTransform.match(/^matrix\(([^)]+)\)$/)
  if (decorationMatrix) {
    const [a, b, c, d] = decorationMatrix[1].split(/[,\s]+/).map(Number)
    assert.ok(Math.abs(b) < 0.001 && Math.abs(c) < 0.001 && Math.abs(a - 1) < 0.001 && Math.abs(d - 1) < 0.001, `${label}: layered document decoration should not rotate the source panel`)
  } else assert.ok(['none', 'matrix(1, 0, 0, 1, 0, 0)'].includes(metrics.sourceDecorationTransform), `${label}: document decoration should use translation only`)
  assert.ok(metrics.pathEnd && metrics.pathEnd.x >= metrics.source.left && metrics.pathEnd.x <= metrics.source.right && metrics.pathEnd.y >= metrics.source.top && metrics.pathEnd.y <= metrics.source.bottom, `${label}: the connected provenance line should terminate at the source document`)
  assert.ok(metrics.source.left > metrics.claim.right && metrics.source.left > metrics.evidence.right, `${label}: compact Claim/Evidence text should lead into the dominant source document without overlapping it`)
  const overlaps = metrics.source.left < metrics.verdict.right && metrics.source.right > metrics.verdict.left && metrics.source.top < metrics.verdict.bottom && metrics.source.bottom > metrics.verdict.top
  assert.equal(overlaps, false, `${label}: source artwork and independent verdict must not overlap: ${JSON.stringify({ source: metrics.source, verdict: metrics.verdict })}`)
  if (metrics.viewportWidth > 520) assert.ok(metrics.verdict.right < metrics.source.left, `${label}: the fourth-step verdict should sit to the left of the source card`)
  else assert.ok(metrics.source.bottom < metrics.verdict.top, `${label}: mobile fourth-step verdict should follow the source card`)
  assert.ok(metrics.verdictPathStart, `${label}: the independent decision line should have a measurable start`)
  if (metrics.verdictCode === 'not_in_evidence') {
    assert.ok(metrics.evidenceEnd && Math.hypot(metrics.verdictPathStart.x - metrics.evidenceEnd.x, metrics.verdictPathStart.y - metrics.evidenceEnd.y) <= 2, `${label}: a missing Claim should route directly from Evidence to the verdict, not through Source`)
  } else {
    assert.ok(metrics.verdictPathStart.x >= metrics.source.left - 1 && metrics.verdictPathStart.x <= metrics.source.right + 1 && metrics.verdictPathStart.y >= metrics.source.top - 1 && metrics.verdictPathStart.y <= metrics.source.bottom + 1, `${label}: the independent decision line should begin at Source 03 (allowing 1 px for transformed SVG edge rounding)`)
  }
  assert.ok(metrics.verdictPathEnd && metrics.verdictPathEnd.x >= metrics.verdict.left - 1 && metrics.verdictPathEnd.x <= metrics.verdict.right + 1 && metrics.verdictPathEnd.y >= metrics.verdict.top - 1 && metrics.verdictPathEnd.y <= metrics.verdict.bottom + 1, `${label}: the independent decision line should terminate inside the fourth-step card, allowing 1 px for transformed SVG edge rounding`)
  if (metrics.viewportWidth > 520) {
    assert.ok(metrics.verdictPathLength > 90, `${label}: the Source-to-verdict path should remain visibly longer than a short connector`)
    assert.ok(metrics.verdictEndpointError <= 1, `${label}: final path endpoint should land at the center of the verdict card's right edge within 1 px: ${JSON.stringify({ end: metrics.verdictPathEnd, target: metrics.verdictTarget, error: metrics.verdictEndpointError })}`)
  }
  assert.ok(metrics.verdictHit, `${label}: the verdict card must remain reachable above the decorative source-to-verdict line`)
  assert.equal(metrics.connectorGeometry.length, 2, `${label}: both evidence connectors should remain visible`)
  for (const connector of metrics.connectorGeometry) {
    assert.ok(connector.gap >= 14, `${label}: ${connector.text} label should stay at least 14 px away from the trace light path; ${JSON.stringify(connector)}`)
    assert.ok(connector.backgroundColor === 'rgba(0, 0, 0, 0)' && connector.backgroundImage === 'none', `${label}: connector labels must not hide the route line with a background; ${JSON.stringify(connector)}`)
  }
  for (const [name, style] of [['Claim', metrics.claimStyle], ['Evidence', metrics.evidenceStyle]]) {
    assert.ok(style && (style.background === 'rgba(0, 0, 0, 0)' || style.background.endsWith(', 0)')), `${label}: ${name} should remain a compact trace label, not a third large card`)
    assert.equal(style.borderStyle, 'none', `${label}: ${name} should not become a boxed card`)
  }
  evidence.traceLayoutChecks.push({ label, ...metrics })
  evidence.sourceAlignmentChecks.push({ label, sourceTransform: metrics.sourceTransform, decorationTransform: metrics.sourceDecorationTransform })
  return metrics
}

async function assertEvidenceMobileFlow(panel) {
  const metrics = await panel.evaluate(root => {
    const archive = root.querySelector('.evidence-archive')
    const trace = archive?.querySelector('.evidence-trace')
    const box = element => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
    }
    return {
      trace: box(trace), claim: box(trace?.querySelector('.trace-claim')), evidence: box(trace?.querySelector('.trace-evidence')),
      source: box(trace?.querySelector('.trace-source')), verdict: box(archive?.querySelector('.trace-verdict')),
      wiringDisplay: getComputedStyle(trace?.querySelector('.trace-wiring')).display,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
    }
  })
  assert.ok(metrics.trace && metrics.claim && metrics.evidence && metrics.source && metrics.verdict, 'Mobile evidence flow should remain measurable')
  assert.equal(metrics.wiringDisplay, 'none', 'Mobile evidence flow should use its compact native vertical connector')
  assert.ok(metrics.claim.top < metrics.evidence.top && metrics.evidence.bottom < metrics.source.top && metrics.source.bottom < metrics.verdict.top, 'Mobile Claim, Evidence, source, and verdict should follow a readable vertical order')
  assert.ok(metrics.source.left >= metrics.trace.left && metrics.source.right <= metrics.trace.right + 1, 'Mobile source document should fit within the trace column')
  assert.ok(metrics.documentWidth <= metrics.viewportWidth + 1, 'Mobile evidence composition should not introduce horizontal overflow')
}

async function assertJourneyComposition(panel) {
  const result = await panel.evaluate(root => {
    const svg = root.querySelector('.journey-map > svg')
    const lanes = [...root.querySelectorAll('.route-lane')]
    const rect = element => {
      const box = element.getBoundingClientRect()
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height }
    }
    const laneData = lanes.map(lane => ({
      learner: lane.dataset.learner,
      box: rect(lane),
      header: rect(lane.querySelector('.journey-profile-select')),
      nodes: [...lane.querySelectorAll('.journey-step')].map(node => ({ id: node.dataset.node, box: rect(node) })),
    }))
    const nodes = new Map(laneData.flatMap(lane => lane.nodes.map(node => [node.id, node.box])))
    const pathFailures = []
    const paths = [...(svg?.querySelectorAll('path[data-from][data-to]') || [])]
    for (const path of paths) {
      const total = path.getTotalLength()
      for (let index = 1; index < 32; index++) {
        const point = svg.createSVGPoint()
        const local = path.getPointAtLength(total * index / 32)
        point.x = local.x
        point.y = local.y
        const screen = point.matrixTransform(svg.getScreenCTM())
        for (const [nodeId, box] of nodes) {
          if (nodeId === path.dataset.from || nodeId === path.dataset.to) continue
          if (screen.x > box.left + 2 && screen.x < box.right - 2 && screen.y > box.top + 2 && screen.y < box.bottom - 2) {
            pathFailures.push({ from: path.dataset.from, to: path.dataset.to, crosses: nodeId, sample: index })
          }
        }
      }
    }
    return { lanes: laneData, paths: paths.length, pointerEvents: svg ? getComputedStyle(svg).pointerEvents : null, pathFailures }
  })
  assert.equal(result.lanes.length, 3, 'The learning graph should use three visible learner columns')
  assert.deepEqual(result.lanes.map(lane => lane.learner), ['0', '1', '2'], 'Learner columns should be ordered from the foundational route to the advanced route')
  assert.ok(result.lanes[0].box.left < result.lanes[1].box.left && result.lanes[1].box.left < result.lanes[2].box.left, 'Learner tiers should occupy distinct left-to-right columns')
  assert.ok(result.lanes.every(lane => Math.abs(lane.box.top - result.lanes[0].box.top) < 2 && Math.abs(lane.box.height - result.lanes[0].box.height) < 2), 'All learner columns should share one aligned vertical frame')
  for (const lane of result.lanes) {
    assert.ok(lane.header.bottom <= lane.nodes[0].box.top, `Tier ${Number(lane.learner) + 1} selector should stay above its vertical node sequence`)
    for (let index = 0; index < lane.nodes.length; index++) {
      const node = lane.nodes[index]
      assert.ok(node.box.left >= lane.box.left && node.box.right <= lane.box.right, `${node.id}: node should remain inside its learner column`)
      if (index) assert.ok(lane.nodes[index - 1].box.top < node.box.top, `Tier ${Number(lane.learner) + 1} nodes should follow their vertical learning order`)
      if (index) assert.ok(lane.nodes[index - 1].box.bottom <= node.box.top, `Tier ${Number(lane.learner) + 1} nodes should not overlap vertically`)
    }
  }
  assert.equal(result.paths, 15, 'The visible route art should preserve all 15 metadata edges')
  assert.equal(result.pointerEvents, 'none', 'Decorative route lines must not intercept node controls')
  assert.deepEqual(result.pathFailures, [], `A prerequisite line must not pass through an unrelated node: ${JSON.stringify(result.pathFailures)}`)
  evidence.journeyCompositionChecks.push({ composition: 'three aligned vertical learner columns; all 15 SVG edges sampled against unrelated node bounds', lanes: result.lanes.map(lane => ({ learner: lane.learner, nodeCount: lane.nodes.length })), sampledEdges: result.paths })
  return result
}

async function assertFeedbackRouteLayout(panel, label) {
  const metrics = await panel.evaluate(root => {
    const canvas = root.querySelector('.feedback-route-canvas')
    const workbench = root.querySelector('.feedback-workbench')
    const path = canvas?.querySelector('.feedback-turn-line')
    const totalLength = path?.getTotalLength() || 0
    const start = path?.getPointAtLength(0)
    const end = path?.getPointAtLength(totalLength)
    const turn = canvas?.querySelector('.feedback-turn-point')
    const svg = canvas?.querySelector('svg')
    const svgBox = svg?.getBoundingClientRect()
    const halo = canvas?.querySelector('.feedback-turn-halo circle')
    const turnLabel = canvas?.querySelector('.feedback-turn-label')
    const turnLabelBox = turnLabel?.getBoundingClientRect()
    const turnX = Number(turn?.getAttribute('cx'))
    const turnY = Number(turn?.getAttribute('cy'))
    const turnScreenY = svgBox ? svgBox.top + turnY / 360 * svgBox.height : null
    const haloLeftScreenX = svgBox && halo ? svgBox.left + (turnX - Number(halo.getAttribute('r'))) / 760 * svgBox.width : null
    const canvasBox = canvas?.getBoundingClientRect()
    const nodes = [...(canvas?.querySelectorAll('.feedback-adjusted-route > li') || [])].map(node => {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, centerX: rect.left + rect.width / 2 }
    })
    return {
      rule: workbench?.dataset.rule || null,
      canvas: canvasBox ? { left: canvasBox.left, right: canvasBox.right, top: canvasBox.top, bottom: canvasBox.bottom } : null,
      nodes,
      pathCount: canvas?.querySelectorAll('.feedback-turn-line').length || 0,
      baselineCount: canvas?.querySelectorAll('.feedback-baseline li').length || 0,
      nodeLetters: [...(canvas?.querySelectorAll('.feedback-adjusted-route .node-letter') || [])].map(node => node.innerText.trim()),
      path: path?.getAttribute('d') || '',
      moveCount: (path?.getAttribute('d')?.match(/[Mm]/g) || []).length,
      start: start ? { x: start.x, y: start.y } : null,
      end: end ? { x: end.x, y: end.y } : null,
      turn: turn ? { x: Number(turn.getAttribute('cx')), y: Number(turn.getAttribute('cy')) } : null,
      turnLabelGap: turnLabelBox && haloLeftScreenX !== null ? haloLeftScreenX - turnLabelBox.right : null,
      turnLabelCenterYDelta: turnLabelBox && turnScreenY !== null ? Math.abs((turnLabelBox.top + turnLabelBox.bottom) / 2 - turnScreenY) : null,
      turnLabelInsideCanvas: Boolean(turnLabelBox && canvasBox && turnLabelBox.left >= canvasBox.left - 0.5 && turnLabelBox.right <= canvasBox.right + 0.5 && turnLabelBox.top >= canvasBox.top - 0.5 && turnLabelBox.bottom <= canvasBox.bottom + 0.5),
    }
  })
  assert.ok(metrics.canvas, `${label}: feedback route canvas should be measurable`)
  assert.equal(metrics.pathCount, 1, `${label}: feedback route should expose one rule-selected path`)
  assert.equal(metrics.nodes.length, 2, `${label}: feedback route should show two adjusted route nodes`)
  assert.equal(metrics.baselineCount, 2, `${label}: abstract current node and original route should remain visible inside the canvas`)
  assert.equal(metrics.moveCount, 1, `${label}: every feedback branch should use the same continuous one-subpath geometry`)
  assert.equal(metrics.path, expectedFeedbackRoutePath, `${label}: every branch should follow the same continuous route`)
  assert.deepEqual(metrics.start, { x: 380, y: 130 }, `${label}: every branch should start from the current learner node`)
  assert.deepEqual(metrics.end, { x: 457, y: 284 }, `${label}: every branch should finish on the right-hand route`)
  assert.deepEqual(metrics.turn, { x: 183.75, y: 165.75 }, `${label}: every branch should share the left quadratic turning point`)
  const expectedLabelGap = await panel.evaluate(() => innerWidth >= 1800 ? 20 : innerWidth <= 520 ? 10 : 16)
  assert.ok(Math.abs(metrics.turnLabelGap - expectedLabelGap) <= 0.5, `${label}: FEEDBACK hint should sit left of the halo with the responsive gap: expected ${expectedLabelGap}px, got ${metrics.turnLabelGap}px`)
  assert.ok(metrics.turnLabelCenterYDelta <= 0.1, `${label}: FEEDBACK hint should be vertically centered on its turning point: ${metrics.turnLabelCenterYDelta}px`)
  assert.ok(metrics.turnLabelInsideCanvas, `${label}: FEEDBACK hint should stay inside the route canvas`)
  assert.ok(metrics.nodes[0].centerX < metrics.nodes[1].centerX, `${label}: every branch should keep its first node left of its second node`)
  for (const [index, node] of metrics.nodes.entries()) {
    assert.ok(node.left >= metrics.canvas.left - 1 && node.right <= metrics.canvas.right + 1 && node.top >= metrics.canvas.top - 1 && node.bottom <= metrics.canvas.bottom + 1, `${label}: adjusted route node ${index + 1} should stay inside the SVG canvas`)
  }
  assert.ok(metrics.nodes[0].right <= metrics.nodes[1].left || metrics.nodes[1].right <= metrics.nodes[0].left || metrics.nodes[0].bottom <= metrics.nodes[1].top || metrics.nodes[1].bottom <= metrics.nodes[0].top, `${label}: adjusted route nodes must not overlap`)
  evidence.feedbackRouteChecks.push({ state: label, canvas: metrics.canvas, routeNodes: metrics.nodes })
  return metrics
}

async function reachable(locator, label) {
  await locator.waitFor({ state: 'visible' })
  await locator.scrollIntoViewIfNeeded()
  const hit = await locator.evaluate(el => {
    const rect = el.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    const top = document.elementFromPoint(x, y)
    return {
      visible: rect.width > 0 && rect.height > 0 && x >= 0 && x < innerWidth && y >= 0 && y < innerHeight,
      unobscured: Boolean(top && (top === el || el.contains(top))),
    }
  })
  assert.ok(hit.visible && hit.unobscured, `${label}: control is clipped or obscured`)
}

function controlsFor(page, feature) {
  const panel = page.locator(`#${feature.id}.showcase-panel`)
  const controls = []
  if (feature.key === 'agents') {
    controls.push(...[
      '查看诊断智能体', '查看规划智能体', '查看生成智能体', '查看审核智能体', '查看Claim智能体',
    ].map(name => panel.getByRole('button', { name, exact: true })))
    controls.push(panel.getByRole('button', { name: '演示一次协作', exact: true }))
  } else if (feature.key === 'evidence') {
    controls.push(...['有证据支持', '当前无依据', '与来源矛盾'].map(label => panel.getByRole('button', { name: `查看判定规则：${label}`, exact: true })))
  } else if (feature.key === 'path') {
    controls.push(...[1, 2, 3].map(tier => panel.getByRole('button', { name: `选择诊断起点：第 ${tier} 阶`, exact: true })))
    controls.push(...metadataNodes.map((_, index) => panel.locator('.journey-step').nth(index)))
  } else if (feature.key === 'feedback') {
    controls.push(...['补基础', '纠错巩固', '继续进阶'].map(name => panel.getByRole('button', { name: `查看反馈规则：${name}`, exact: true })))
    controls.push(...[
      '测评依据', '路线重排', '确认后学习',
    ].map(name => panel.getByRole('button', { name: `查看反馈步骤：${name}`, exact: true })))
    controls.push(panel.getByRole('button', { name: '继续演示', exact: true }))
  }
  return controls
}

async function assertDemoMark(page, feature) {
  const marker = page.locator(`#${feature.id}.showcase-panel .feature-demo-note`)
  await marker.waitFor({ state: 'visible' })
  const text = (await marker.innerText()).trim()
  assert.match(text, /项目机制示意/, `${feature.id}: missing visible project-mechanism marker`)
  if (feature.key === 'agents') assert.match(text, /可选 Claim 分支/, 'Agent demonstration marker should disclose its optional Claim branch')
  return text
}

async function screenshot(page, feature, viewport) {
  if (feature.key === 'evidence') await waitForEvidenceVerdictReady(page, `screenshot/${viewport.name}`)
  await waitForVisualStability(page)
  const filename = `${feature.key}-${viewport.name}.png`
  const buffer = await page.screenshot({ path: path.join(reportDir, filename), fullPage: false })
  const dimensions = { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) }
  const expectedWidth = Math.ceil(viewport.width * (viewport.scale || 1))
  const expectedHeight = Math.ceil(viewport.height * (viewport.scale || 1))
  assert.equal(dimensions.width, expectedWidth, `${filename}: wrong screenshot width`)
  assert.equal(dimensions.height, expectedHeight, `${filename}: wrong screenshot height`)
  evidence.screenshots.push({ filename, ...dimensions, viewport: { width: viewport.width, height: viewport.height, scale: viewport.scale || 1 } })
}

async function readEvidenceVisualFrame(archive, atPhase = null) {
  return archive.evaluate(async (element, phase) => {
    if (phase !== null && element.dataset.phase !== String(phase)) {
      // Capture the phase boundary in the same browser microtask as its DOM update.
      // A waitForFunction + evaluate round trip can miss the initial animation frame.
      await new Promise((resolve, reject) => {
        const observer = new MutationObserver(() => {
          if (element.dataset.phase === String(phase)) {
            observer.disconnect()
            clearTimeout(timeout)
            resolve()
          }
        })
        const timeout = setTimeout(() => { observer.disconnect(); reject(new Error('Phase-boundary sample timed out')) }, 5000)
        observer.observe(element, { attributes: true, attributeFilter: ['data-phase'] })
      })
    }
    const path = element.querySelector('.trace-signal')
    const marker = element.querySelector('.trace-light-point')
    const transform = marker?.getAttribute('transform') || ''
    const markerPoint = transform.match(/translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)/)
    const pathLength = path?.getTotalLength() || 0
    const traceProgress = Number(element.dataset.traceProgress)
    const expected = path?.getPointAtLength(pathLength * traceProgress)
    const verdictPath = element.querySelector('.verdict-wiring .trace-signal')
    const verdictMarker = element.querySelector('.verdict-wiring .trace-light-point')
    const verdictTransform = verdictMarker?.getAttribute('transform') || ''
    const verdictPointMatch = verdictTransform.match(/translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)/)
    const verdictPathLength = verdictPath?.getTotalLength() || 0
    const verdictProgress = Number(element.dataset.verdictProgress)
    const expectedVerdictPoint = verdictPath?.getPointAtLength(verdictPathLength * verdictProgress)
    return {
      phase: Number(element.dataset.phase),
      cycle: Number(element.dataset.cycle),
      playing: element.dataset.playing === 'true',
      rule: element.dataset.verdict || null,
      traceProgress,
      phaseProgress: Number(element.dataset.phaseProgress),
      pathLength,
      moveCount: (path?.getAttribute('d')?.match(/[Mm]/g) || []).length,
      marker: markerPoint ? { x: Number(markerPoint[1]), y: Number(markerPoint[2]) } : null,
      expected: expected ? { x: expected.x, y: expected.y } : null,
      dashOffset: Number(path?.style.strokeDashoffset),
      verdictReady: element.dataset.verdictReady === 'true',
      verdictProgress,
      verdictPathLength,
      verdictMoveCount: (verdictPath?.getAttribute('d')?.match(/[Mm]/g) || []).length,
      verdictMarker: verdictPointMatch ? { x: Number(verdictPointMatch[1]), y: Number(verdictPointMatch[2]) } : null,
      expectedVerdictPoint: expectedVerdictPoint ? { x: expectedVerdictPoint.x, y: expectedVerdictPoint.y } : null,
      verdictDashOffset: Number(verdictPath?.style.strokeDashoffset),
      verdictMarkerOpacity: Number(getComputedStyle(verdictMarker).opacity),
      verdictStart: verdictPath?.getPointAtLength(0) ? { x: verdictPath.getPointAtLength(0).x, y: verdictPath.getPointAtLength(0).y } : null,
      verdictEnd: expectedVerdictPoint ? { x: verdictPath.getPointAtLength(verdictPathLength).x, y: verdictPath.getPointAtLength(verdictPathLength).y } : null,
      markerOpacity: Number(getComputedStyle(marker).opacity),
      evidenceState: element.querySelector('.trace-evidence')?.classList.contains('is-active') ? 'active' : 'pending',
      evidenceTitleColor: getComputedStyle(element.querySelector('.trace-evidence h3')).color,
      sourceState: element.querySelector('.trace-source')?.dataset.sourceState || null,
      sourceActive: element.querySelector('.trace-source')?.classList.contains('is-active') || false,
      sourceReached: element.querySelector('.trace-source')?.classList.contains('is-reached') || false,
      sourceTitleColor: getComputedStyle(element.querySelector('.trace-source h3')).color,
      sourceBorderColor: getComputedStyle(element.querySelector('.trace-source')).borderColor,
      verdictReached: element.querySelector('.trace-verdict')?.dataset.reached === 'true',
      verdictLabel: element.querySelector('.trace-verdict-result strong')?.innerText.trim() || '',
      verdictCardReady: element.querySelector('.trace-verdict')?.classList.contains('is-ready') || false,
      verdictBorderColor: getComputedStyle(element.querySelector('.trace-verdict')).borderColor,
      verdictBackgroundColor: getComputedStyle(element.querySelector('.trace-verdict')).backgroundColor,
      verdictLabelColor: getComputedStyle(element.querySelector('.trace-verdict-result strong')).color,
      duplicateVerdictStepCount: element.querySelectorAll('.trace-final-step').length,
      topVerdictNumberCount: [...element.querySelectorAll('.trace-verdict .trace-code')].filter(node => /\b04\b/.test(node.innerText)).length,
      finalLightOpacity: Number(getComputedStyle(verdictMarker).opacity),
    }
  }, atPhase)
}

function assertEvidenceVisualFrame(frame, label) {
  assert.equal(frame.duplicateVerdictStepCount, 0, `${label}: the duplicate numbered verdict step should not exist in the DOM`)
  assert.equal(frame.topVerdictNumberCount, 1, `${label}: the verdict should show exactly one 04 in its top label`)
  assert.ok(frame.marker && frame.expected, `${label}: trace marker and path point should be measurable`)
  assert.ok(Math.hypot(frame.marker.x - frame.expected.x, frame.marker.y - frame.expected.y) <= 0.03, `${label}: marker and trace should use the same progress: ${JSON.stringify(frame)}`)
  assert.equal(frame.moveCount, 1, `${label}: the Claim-to-Source trace should remain one continuous subpath`)
  assert.ok(Math.abs(frame.dashOffset - (1 - frame.traceProgress)) <= 0.00002, `${label}: trace stroke and marker should share progress`)
  if (frame.verdictPathLength > 0) {
    assert.ok(frame.verdictMarker && frame.expectedVerdictPoint, `${label}: terminal light and verdict path point should be measurable`)
    assert.equal(frame.verdictMoveCount, 1, `${label}: the Source-to-verdict connection should be one continuous subpath`)
    assert.ok(Math.hypot(frame.verdictMarker.x - frame.expectedVerdictPoint.x, frame.verdictMarker.y - frame.expectedVerdictPoint.y) <= 0.03, `${label}: terminal light and verdict path should use the same progress: ${JSON.stringify(frame)}`)
    assert.ok(Math.abs(frame.verdictDashOffset - (1 - frame.verdictProgress)) <= 0.00002, `${label}: terminal path stroke should follow verdict progress`)
  }
}

async function focusEvidenceRuleByKeyboard(page, locator, label) {
  await page.locator('#evidence-title').focus()
  for (let index = 0; index < 24; index++) {
    await page.keyboard.press('Tab')
    if (await locator.evaluate(element => element === document.activeElement)) {
      assert.equal(await locator.evaluate(element => element.matches(':focus-visible')), true, `${label}: Tab focus must use keyboard modality`)
      return
    }
  }
  throw new Error(`${label}: keyboard Tab sequence did not reach the Evidence rule`)
}

async function contrast(page, locator, label, minimum = 4.5) {
  const result = await locator.evaluate(el => {
    const parseColor = value => {
      const match = value.match(/^rgba?\((.+)\)$/)
      if (!match) throw new Error(`Unsupported computed color: ${value}`)
      const channels = match[1].trim().split(/[\s,/]+/).map(Number.parseFloat)
      return { r: channels[0], g: channels[1], b: channels[2], a: channels.length > 3 ? channels[3] : 1 }
    }
    const composite = (foreground, background) => {
      const alpha = foreground.a + background.a * (1 - foreground.a)
      if (!alpha) return { r: 0, g: 0, b: 0, a: 0 }
      return {
        r: (foreground.r * foreground.a + background.r * background.a * (1 - foreground.a)) / alpha,
        g: (foreground.g * foreground.a + background.g * background.a * (1 - foreground.a)) / alpha,
        b: (foreground.b * foreground.a + background.b * background.a * (1 - foreground.a)) / alpha,
        a: alpha,
      }
    }
    const luminance = ({ r, g, b }) => [r, g, b].map(value => {
      const channel = value / 255
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
    }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
    const root = document.querySelector('.landing-page')
    if (!root || !root.contains(el)) throw new Error('Contrast target is outside the landing page')

    let background = parseColor(getComputedStyle(root).backgroundColor)
    if (background.a < 1) throw new Error('Landing root must provide an opaque theme background')
    const layers = [{ selector: '.landing-page', color: getComputedStyle(root).backgroundColor }]
    const ancestors = []
    for (let current = el; current && current !== root; current = current.parentElement) ancestors.push(current)
    for (const current of ancestors.reverse()) {
      const value = getComputedStyle(current).backgroundColor
      const layer = parseColor(value)
      if (layer.a > 0) {
        background = composite(layer, background)
        layers.push({ selector: current.tagName.toLowerCase() + (current.classList.length ? `.${[...current.classList].join('.')}` : ''), color: value })
      }
    }
    const foregroundColor = getComputedStyle(el).color
    const foreground = composite(parseColor(foregroundColor), background)
    const foregroundL = luminance(foreground)
    const backgroundL = luminance(background)
    return {
      color: foregroundColor,
      background: `rgb(${background.r},${background.g},${background.b})`,
      backgroundLayers: layers,
      ratio: (Math.max(foregroundL, backgroundL) + 0.05) / (Math.min(foregroundL, backgroundL) + 0.05),
    }
  })
  assert.ok(result.ratio >= minimum, `${label}: contrast ${result.ratio.toFixed(2)} below ${minimum}`)
  evidence.contrastChecks.push({ label, ...result })
  return result
}

async function verifyTheme(page, feature) {
  const theme = await page.evaluate(() => {
    const root = document.querySelector('.landing-page')
    const nav = document.querySelector('.landing-nav')
    const active = document.querySelector(`${location.hash}.showcase-panel[data-feature]`)
    return {
      name: root?.dataset.theme || null,
      navBackground: nav ? getComputedStyle(nav).backgroundColor : null,
      panelBackground: active ? getComputedStyle(active).backgroundColor : null,
      rootBackground: root ? getComputedStyle(root).backgroundColor : null,
      brandColor: root ? getComputedStyle(root.querySelector('.landing-brand strong')).color : null,
    }
  })
  assert.equal(theme.name, feature.key, `${feature.id}: top navigation should follow the active feature theme`)
  assert.equal(theme.navBackground, theme.panelBackground, `${feature.id}: top navigation should share the active feature background`)
  assert.ok(theme.brandColor, `${feature.id}: themed brand text should be visible`)
  await contrast(page, page.locator('.landing-brand strong'), feature.id + ' themed navigation brand')
  await contrast(page, page.locator('.landing-brand small'), feature.id + ' themed navigation subtitle')
  assert.equal(await page.locator('.landing-nav .nav-feature-link').count(), 0, 'Top navigation must not repeat the capabilities link')
  await contrast(page, page.locator('.login-trigger'), feature.id + ' themed login control')
  evidence.themeChecks.push({ feature: feature.key, ...theme })
}

async function verifyFocus(page, feature) {
  const target = page.locator('#' + feature.id + '.showcase-panel button').first()
  let focused = false
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press('Tab')
    if (await target.evaluate(el => el === document.activeElement)) {
      focused = true
      break
    }
  }
  assert.ok(focused, feature.id + ': keyboard tab order did not reach a showcase control')
  const result = await target.evaluate(el => {
    const style = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    return {
      focusVisible: el.matches(':focus-visible'),
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
      boxShadow: style.boxShadow,
      inViewport: rect.top >= 0 && rect.bottom <= innerHeight && rect.left >= 0 && rect.right <= innerWidth,
    }
  })
  assert.ok(result.focusVisible && result.inViewport, feature.id + ': keyboard focus is not visible')
  assert.ok((result.outlineStyle !== 'none' && result.outlineWidth >= 1) || result.boxShadow !== 'none', feature.id + ': focused control has no visible indicator')
  evidence.focusChecks.push({ feature: feature.key, ...result })
}

async function verifyInteractions(page, feature) {
  await assertDemoMark(page, feature)
  const panel = page.locator('#' + feature.id + '.showcase-panel')
  if (feature.key === 'agents') {
    const labels = ['诊断', '规划', '生成', '审核', 'Claim']
    const expectedIo = {
      诊断: ['学习者画像', '诊断摘要'],
      规划: ['画像 + 证据', '资源计划'],
      生成: ['资源规格', '学习资源'],
      审核: ['资源 + 证据', '审核决定'],
      Claim: ['陈述 + 证据', '逐条判定'],
    }
    const descriptions = []
    assert.equal(await panel.locator('.agent-role').count(), labels.length, 'The constellation should show only actual Agent roles, without promoting retrieval to an Agent')
    assert.equal(await panel.getByRole('button', { name: '查看检索智能体', exact: true }).count(), 0, 'Retrieval is a workflow step, not an LLM Agent')
    assert.match(await panel.locator('.agent-core small').innerText(), /SHARED STATE/)
    assert.match(await panel.locator('.agent-core').innerText(), /工作流上下文/)
    assert.match((await panel.locator('.agent-core').innerText()).replace(/\s+/g, ' '), /画像.*证据.*资源/)
    assert.ok(await panel.locator('.agent-io').count(), 'Selected Agent should expose input and output fields')
    for (const role of labels) {
      await panel.getByRole('button', { name: '查看' + role + '智能体', exact: true }).click()
      const rolePanel = panel.locator('[data-role-panel]')
      await rolePanel.waitFor({ state: 'visible' })
      assert.equal((await rolePanel.locator('h3').innerText()).trim(), role + ' Agent', role + ' panel should identify the actual Agent role')
      const io = (await rolePanel.locator('.agent-io').innerText()).trim()
      assert.match(io, /IN[\s\S]+OUT[\s\S]+/, role + ' Agent should show both shared-workflow input and output')
      for (const field of expectedIo[role]) assert.ok(io.includes(field), `${role} Agent should retain the real input/output field: ${field}`)
      const detail = (await rolePanel.locator('p').innerText()).trim()
      assert.ok(detail, role + ' Agent role description should be visible')
      descriptions.push(detail)
      await verifySelectedStateFits(page, feature)
    }
    assert.equal(new Set(descriptions).size, labels.length, 'Agent role selections should show distinct responsibility descriptions')
    assert.match(await panel.getByRole('button', { name: '查看Claim智能体', exact: true }).innerText(), /可选/, 'Claim branch should be explicitly optional')

    const diagnosis = panel.getByRole('button', { name: '查看诊断智能体', exact: true })
    await panel.getByRole('button', { name: '演示一次协作', exact: true }).click()
    const pause = panel.getByRole('button', { name: '暂停演示', exact: true })
    await pause.waitFor({ state: 'visible' })
    assert.equal(await diagnosis.getAttribute('aria-pressed'), 'true', 'Collaboration demo should start at diagnosis')
    await page.waitForFunction(() => document.querySelector('#multi-agent [data-role-panel] h3')?.innerText === '规划 Agent')
    await pause.click()
    await panel.getByRole('button', { name: '继续演示', exact: true }).waitFor({ state: 'visible' })
    const planner = panel.getByRole('button', { name: '查看规划智能体', exact: true })
    assert.equal(await planner.getAttribute('aria-pressed'), 'true', 'Pausing should preserve the active Agent role')
    assert.equal((await panel.locator('[data-role-panel] h3').innerText()).trim(), '规划 Agent')
    await panel.getByRole('button', { name: '继续演示', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('#multi-agent [role="status"]')?.innerText.includes('协作示意完成'))
    assert.equal(await panel.getByRole('button', { name: '查看Claim智能体', exact: true }).getAttribute('aria-pressed'), 'true', 'Completion should reach the optional Claim branch')
    assert.match(await panel.locator('[role="status"]').innerText(), /Claim 为可选分支/)
    evidence.interactions.push({ feature: feature.key, roles: labels, sharedState: 'SHARED STATE with workflow context, image/evidence/resources', pauseResume: 'paused on planner, preserved selection, resumed through review to optional Claim' })
  } else if (feature.key === 'evidence') {
    const rules = [
      { label: '有证据支持', code: 'supported', evidenceText: /仅允许证据白名单内的 ID/, ruleText: /必须绑定有效 Evidence ID/ },
      { label: '当前无依据', code: 'not_in_evidence', evidenceText: /不绑定 Evidence ID/, ruleText: /不会用一个无关引用冒充支持/ },
      { label: '与来源矛盾', code: 'contradicted', evidenceText: /仅允许证据白名单内的 ID/, ruleText: /同样必须关联有效证据/ },
    ]
    const records = []
    assert.equal(await panel.locator('a').count(), 0, 'Evidence mechanism view must not expose external source links')
    assert.equal(await panel.locator('.source-original').count(), 0, 'Paper/source example links must be removed')
    for (let index = 0; index < rules.length; index++) {
      const rule = rules[index]
      if (index > 0) {
        await panel.getByRole('button', { name: '继续溯源演示', exact: true }).click()
        await page.waitForFunction(() => document.querySelector('#evidence .evidence-archive')?.dataset.playing === 'true')
      }
      const choice = panel.getByRole('button', { name: '查看判定规则：' + rule.label, exact: true })
      await choice.click()
      assert.equal(await choice.getAttribute('aria-pressed'), 'true', 'Selected claim-verdict rule should be announced')
      const archive = panel.locator('.evidence-archive')
      assert.equal(await archive.getAttribute('data-verdict'), rule.code, 'Trace should expose the selected formal Claim verdict')
      assert.equal(await archive.getAttribute('data-phase'), '0', 'Changing the verdict rule should restart at Claim')
      assert.equal(await archive.getAttribute('data-cycle'), '0', 'Changing the verdict rule should reset the automatic loop cycle')
      assert.equal(await archive.getAttribute('data-playing'), 'true', 'A real pointer rule change should restart automatic tracing')
      const finalResult = await waitForEvidenceVerdictReady(page, `interaction/${rule.code}`)
      assert.equal(finalResult.rule, rule.code, `${rule.code}: the terminal-light result should match the selected Claim rule`)
      assert.equal(finalResult.verdict, rule.label, `${rule.code}: the final verdict should use the selected rule label`)
      assert.equal(finalResult.sourceState, rule.code === 'not_in_evidence' ? 'unbound' : 'located', `${rule.code}: the source locator must preserve the selected evidence policy`)
      await archive.locator('.trace-verdict-result strong').evaluate(async element => {
        const colorTransition = element.getAnimations().find(animation => animation.transitionProperty === 'color')
        if (colorTransition) await colorTransition.finished.catch(() => undefined)
      })
      const finalVisual = await archive.locator('.trace-verdict').evaluate(element => ({
        reached: element.dataset.reached === 'true',
        ready: element.classList.contains('is-ready'),
        borderColor: getComputedStyle(element).borderColor,
        labelColor: getComputedStyle(element.querySelector('.trace-verdict-result strong')).color,
      }))
      assert.equal(finalVisual.reached, true, `${rule.code}: the independent fourth-step verdict should be reached`)
      assert.equal(finalVisual.ready, true, `${rule.code}: the completed verdict card should be highlighted`)
      const record = {
        claim: (await panel.locator('.trace-claim').innerText()).trim(),
        evidence: (await panel.locator('.trace-evidence').innerText()).trim(),
        source: (await panel.locator('.trace-source').innerText()).trim(),
        verdict: (await panel.locator('.trace-verdict').innerText()).trim(),
        rule: (await panel.locator('.claim-rule-detail').innerText()).trim(),
        demoMark: await panel.locator('.feature-demo-note').innerText(),
        finalVisual,
      }
      assert.match(record.claim, /Claim|陈述|原文区间/)
      assert.match(record.claim, /哈希/)
      assert.match(record.evidence, /EVIDENCE/)
      assert.match(record.evidence, rule.evidenceText, 'Evidence association must follow the selected verdict rule')
      assert.match(record.source, /知识库[\s·]*文档版本[\s·]*Chunk/)
      assert.match(record.source, /章节.*行号/)
      assert.match(record.source, /摘录哈希/)
      assert.match(record.verdict, new RegExp(rule.label))
      assert.match(record.rule, rule.ruleText)
      assert.match(record.demoMark, /项目机制示意/)
      records.push(record)
      await assertEvidenceComposition(panel, `evidence/${rule.code}`)
      await verifySelectedStateFits(page, feature)
    }
    assert.equal(new Set(records.map(record => record.finalVisual.labelColor)).size, 3, 'The three final Claim decisions should each use their distinct result color')
    assert.equal(await panel.locator('a[href^="http"]').count(), 0, 'Evidence panel must contain no external URLs')
    assert.doesNotMatch((await panel.innerText()), /arXiv|Sentence-BERT|RAGTruth|https?:\/\//i, 'Evidence panel must not contain papers, invented examples, or external URLs')
    evidence.interactions.push({ feature: feature.key, verdicts: rules.map(({ label, code }) => ({ label, code })), traceFields: records })
  } else if (feature.key === 'path') {
    const lanes = panel.locator('.route-lane')
    assert.equal(await lanes.count(), 3, 'All diagnostic tiers should be visible together')
    const projectedNodes = []
    for (let index = 0; index < 3; index++) {
      const lane = lanes.nth(index)
      assert.equal(await lane.getAttribute('data-learner'), String(index), 'Learner lane ordering should be stable')
      assert.ok(await lane.isVisible(), 'Every learner route should be visible at once')
      const tier = index + 1
      const expectedNodes = metadataNodes.filter(node => node.tier === tier)
      const laneNodes = await lane.locator('.journey-step').evaluateAll(elements => elements.map(element => ({
        id: element.dataset.node,
        tier: Number(element.dataset.tier),
        prerequisites: element.dataset.prerequisites || '',
        name: element.querySelector(':scope > span')?.innerText.trim(),
      })))
      assert.deepEqual(laneNodes.map(node => node.id), expectedNodes.map(node => node.node_id), `Tier ${tier} must show the metadata nodes in source order`)
      for (let nodeIndex = 0; nodeIndex < expectedNodes.length; nodeIndex++) {
        const expected = expectedNodes[nodeIndex]
        const shown = laneNodes[nodeIndex]
        assert.equal(shown.name, expected.name, `${expected.node_id}: displayed node label must match metadata`)
        assert.equal(shown.tier, expected.tier, `${expected.node_id}: displayed tier must match metadata`)
        assert.equal(shown.prerequisites, (expected.prerequisites || []).map(metadataPrerequisiteId).join(','), `${expected.node_id}: displayed prerequisites must match metadata`)
        projectedNodes.push(shown.id)
      }
    }
    assert.equal(projectedNodes.length, 13, 'The default knowledge graph must project all 13 skill nodes')
    assert.deepEqual(new Set(projectedNodes), new Set(metadataNodes.map(node => node.node_id)), 'Displayed node IDs must exactly equal default knowledge-base metadata')
    const displayedEdges = await panel.locator('svg [data-from][data-to]').evaluateAll(elements => elements.map(element => ({ from: element.dataset.from, to: element.dataset.to })))
    const edgeKey = edge => `${edge.from}->${edge.to}`
    assert.equal(metadataEdges.length, 15, 'Default knowledge-base metadata should define 15 prerequisite edges in version 2.3.0')
    assert.equal(displayedEdges.length, metadataEdges.length, 'The default graph should display every prerequisite edge from metadata')
    assert.deepEqual(displayedEdges.map(edgeKey).sort(), metadataEdges.map(edgeKey).sort(), 'Displayed prerequisite edges must exactly match metadata')
    await assertJourneyComposition(panel)
    const tierStarts = ['rag_basics', 'chunking', 'hybrid_retrieval']
    const selectedTiers = []
    for (let index = 0; index < tierStarts.length; index++) {
      const tier = index + 1
      const choice = panel.getByRole('button', { name: `选择诊断起点：第 ${tier} 阶`, exact: true })
      await choice.click()
      const lane = lanes.nth(index)
      assert.equal(await choice.getAttribute('aria-pressed'), 'true', 'Selected diagnostic tier should be announced')
      assert.ok((await lane.getAttribute('class')).split(/\s+/).includes('is-selected'), 'Selected diagnostic tier should be highlighted')
      const activeStart = lane.locator('.journey-step[aria-pressed="true"]')
      assert.equal(await activeStart.getAttribute('data-node'), tierStarts[index], `Tier ${tier} should start at its configured diagnostic node`)
      const label = (await panel.locator('.journey-profile .journey-current-label').innerText()).trim()
      const startNode = metadataNodes.find(node => node.node_id === tierStarts[index])
      assert.match(label, new RegExp(startNode.name))
      assert.match(label, new RegExp(`第 ${tier} 阶`))
      const exemptions = []
      for (let lower = 0; lower < 3; lower++) {
        const lowerLane = lanes.nth(lower)
        const isExempt = (await lowerLane.getAttribute('class')).split(/\s+/).includes('is-exempt')
        assert.equal(isExempt, lower < index, `Tier ${lower + 1} exemption should follow the selected diagnostic tier`)
        if (isExempt) {
          const labelText = (await lowerLane.locator('.journey-profile-select').innerText()).trim()
          assert.match(labelText, /定阶豁免.*未以测评验证/)
          assert.doesNotMatch(labelText, /已掌握/)
          exemptions.push(lower + 1)
        }
      }
      selectedTiers.push({ tier, start: tierStarts[index], exemptions })
      await verifySelectedStateFits(page, feature)
    }
    assert.match((await panel.locator('.journey-profile').innerText()), /定阶豁免不等于已掌握/)
    assert.match((await panel.locator('.journey-profile').innerText()), /本阶节点完成后，才解锁下一阶/)
    const nodeSelectionChecks = []
    for (const node of metadataNodes) {
      const choice = panel.locator(`.journey-step[data-node="${node.node_id}"]`)
      await choice.click()
      assert.equal(await choice.getAttribute('aria-pressed'), 'true', `${node.node_id}: selected node should be exposed`)
      const expectedPrerequisiteNames = (node.prerequisites || []).map(value => metadataNodes.find(item => item.node_id === value)?.name || value)
      const prerequisiteDetail = (await panel.locator('.journey-profile h3').innerText()).trim()
      if (expectedPrerequisiteNames.length) {
        assert.ok(expectedPrerequisiteNames.every(name => prerequisiteDetail.includes(name)), `${node.node_id}: selected node should show its real prerequisites`)
      } else {
        assert.match(prerequisiteDetail, /先修：无/)
      }
      nodeSelectionChecks.push({ node: node.node_id, prerequisites: expectedPrerequisiteNames })
      await verifySelectedStateFits(page, feature)
    }
    assert.match(await panel.locator('.feature-demo-note').innerText(), /默认 RAG 图谱/)
    evidence.metadataProjectionChecks.push({ knowledgeBase: trainingMetadata.knowledge_base_id, version: trainingMetadata.version, nodes: projectedNodes.length, edges: displayedEdges.length, selectedTiers })
    evidence.interactions.push({ feature: feature.key, tiers: selectedTiers, nodeSelectionChecks })
  } else if (feature.key === 'feedback') {
    const headline = (await panel.locator('h2').innerText()).replace(/\s+/g, ' ')
    assert.match(headline, /反馈/, 'The feedback screen title should name feedback')
    assert.match(headline, /转折/, 'The feedback screen title should make the route change explicit')
    const rules = [
      { label: '补基础', code: 'remediate', condition: /低于 60%/, route: /回溯未掌握前置/, constraint: /候选受实际先修关系约束/, baseline: /暂缓后续学习/, required: ['学习节点 B', '学习节点 A'], letters: ['B', 'A'] },
      { label: '纠错巩固', code: 'practice', condition: /60%.*低于 80%.*无节点阻断/, route: /纠错包只围绕本次测评/, constraint: /配套分阶新题/, baseline: /先巩固，再决定/, required: ['个性化纠错训练包', '学习节点 A'], letters: ['↺', 'A'] },
      { label: '继续进阶', code: 'advance', condition: /80%.*无知识点低于 60%/, route: /只有本阶全部节点完成才解锁下一阶/, constraint: /B 须已解锁且(?:先修|前置)满足/, baseline: /校验可学条件/, required: ['学习节点 A', '学习节点 B'], letters: ['A', 'B'] },
    ]
    const outcomes = []
    assert.equal(await panel.locator('.feedback-playback').getAttribute('aria-label'), '继续演示', 'Stable feature interaction checks should keep automatic feedback paused')
    assert.equal(await panel.locator('.feedback-workbench [aria-live], .feedback-workbench [role="status"], .feedback-workbench [role="alert"]').count(), 0, 'Animated feedback phases must not create a repeatedly announced live region')
    assert.equal(await panel.locator('.feedback-status').getAttribute('aria-live'), null, 'Automatic phase status should not be a live region')
    assert.equal(await panel.locator('.feedback-status').getAttribute('role'), null, 'Automatic phase status should remain non-announcing')
    for (const rule of rules) {
      const choice = panel.getByRole('button', { name: '查看反馈规则：' + rule.label, exact: true })
      await choice.click()
      assert.equal(await choice.getAttribute('aria-pressed'), 'true', 'Selected formal feedback rule should be announced')
      const workbench = panel.locator('.feedback-workbench')
      assert.equal(await workbench.getAttribute('data-rule'), rule.code, 'Formal feedback branch should match the selected threshold rule')
      const values = {
        observation: (await panel.locator('.feedback-observation').innerText()).trim(),
        training: (await panel.locator('.feedback-training').innerText()).trim(),
        verification: (await panel.locator('.feedback-verification').innerText()).trim(),
        route: (await panel.locator('.feedback-adjusted-route').innerText()).trim(),
        baseline: (await panel.locator('.feedback-baseline').innerText()).trim(),
      }
      assert.match(values.observation, rule.condition, rule.label + ': assessment threshold/blocker condition should be explicit')
      assert.match(values.training, rule.route, rule.label + ': route must describe the appropriate remedy')
      assert.match(values.training, rule.constraint, rule.label + ': route must retain the formal prerequisite/assessment constraints')
      for (const required of rule.required) assert.ok(values.route.includes(required), `${rule.label}: expected route element ${required}`)
      assert.match(values.verification, /确认.*才生成下一批资源/)
      assert.match(values.baseline, /学习节点 A[\s\S]*本轮学习节点/)
      assert.match(values.baseline, rule.baseline, `${rule.label}: the original route should identify how A changes under this rule`)
      for (const required of rule.required) assert.ok(values.route.includes(required), `${rule.label}: expected abstract route element ${required}`)
      const routeArt = panel.locator('.feedback-route-canvas')
      const turnLine = routeArt.locator('.feedback-turn-line')
      assert.equal(await routeArt.locator('svg').count(), 1, `${rule.label}: route adjustment should use its original SVG canvas`)
      assert.equal(await turnLine.count(), 1, `${rule.label}: route canvas should show one selected adjustment path`)
      assert.equal(await routeArt.locator('.feedback-base-line').count(), 1, `${rule.label}: route canvas should retain the project prerequisite direction`)
      assert.equal(await routeArt.locator('.feedback-adjusted-route li').count(), 2, `${rule.label}: the route canvas should show both decision nodes`)
      assert.equal(await routeArt.locator('svg').evaluate(el => getComputedStyle(el).pointerEvents), 'none', `${rule.label}: decorative route SVG must not intercept the native stage button`)
      const routeLayout = await assertFeedbackRouteLayout(panel, `desktop/${rule.code}`)
      assert.deepEqual(routeLayout.nodeLetters, rule.letters, `${rule.label}: A/B identities should describe prerequisite, practice, and successor roles accurately`)
      outcomes.push({ code: rule.code, routePath: await turnLine.getAttribute('d'), ...values })
      await verifySelectedStateFits(page, feature)
    }
    for (const key of ['observation', 'training', 'verification', 'route']) assert.equal(new Set(outcomes.map(outcome => outcome[key])).size, 3, `Selecting each formal feedback rule should update ${key}`)
    assert.equal(new Set(outcomes.map(outcome => outcome.routePath)).size, 1, 'All three feedback rules should share the same continuous path geometry')
    const stepNames = ['测评依据', '路线重排', '确认后学习']
    const describedBy = ['feedback-condition', 'feedback-route-title feedback-route-description feedback-route-constraint', 'feedback-confirmation']
    for (let index = 0; index < stepNames.length; index++) {
      const step = panel.locator('[data-feedback-step="' + index + '"]')
      assert.equal(await step.evaluate(el => el.tagName), 'BUTTON', `${stepNames[index]} should remain a native button`)
      assert.equal(await step.getAttribute('aria-label'), '查看反馈步骤：' + stepNames[index])
      assert.equal(await step.getAttribute('aria-describedby'), describedBy[index], `${stepNames[index]} should point to its explanatory content`)
      await step.click()
      assert.equal(await step.getAttribute('aria-pressed'), 'true', 'Selected feedback boundary should be announced')
      assert.ok((await panel.locator('[data-feedback-status]').innerText()).trim(), 'Feedback step should expose its current status')
      await verifySelectedStateFits(page, feature)
    }
    evidence.interactions.push({ feature: feature.key, rules: outcomes, steps: stepNames, liveRegionCount: 0, playback: 'static review completed with autoplay paused' })
  }
}

async function readAgentVisualFrame(scene) {
  return scene.evaluate(element => {
    const roles = [...element.querySelectorAll('.agent-role')]
    const connections = [...element.querySelectorAll('.agent-connection')]
    return {
      running: element.classList.contains('is-running'),
      complete: element.classList.contains('is-complete'),
      selectedIndices: roles.flatMap((role, index) => role.getAttribute('aria-pressed') === 'true' ? [index] : []),
      activeConnectionIndices: connections.flatMap((connection, index) => connection.classList.contains('is-active') ? [index] : []),
      roles: roles.map(role => ({
        selected: role.getAttribute('aria-pressed') === 'true',
        backgroundColor: getComputedStyle(role).backgroundColor,
        borderColor: getComputedStyle(role).borderColor,
        boxShadow: getComputedStyle(role).boxShadow,
        iconColor: getComputedStyle(role.querySelector('.agent-role-icon')).color,
        textColor: getComputedStyle(role.querySelector('.agent-role-copy strong')).color,
      })),
      connections: connections.map(connection => ({
        active: connection.classList.contains('is-active'),
        opacity: getComputedStyle(connection).opacity,
        strokeWidth: getComputedStyle(connection).strokeWidth,
      })),
      status: element.querySelector('[role="status"]')?.innerText.trim() || '',
    }
  })
}

async function inspectAgentOrbit(scene) {
  return scene.evaluate(element => {
    const sceneBox = element.getBoundingClientRect()
    const core = element.querySelector('.agent-core')
    const coreBox = core.getBoundingClientRect()
    const coreScreenCenter = { x: coreBox.left + coreBox.width / 2, y: coreBox.top + coreBox.height / 2 }
    const svg = element.querySelector('svg')
    const svgBox = svg.getBoundingClientRect()
    const roles = [...element.querySelectorAll('.agent-role')].map(role => {
      const box = role.getBoundingClientRect()
      return {
        label: role.getAttribute('aria-label'),
        rect: { left: box.left - sceneBox.left, top: box.top - sceneBox.top, right: box.right - sceneBox.left, bottom: box.bottom - sceneBox.top, width: box.width, height: box.height },
        center: { x: box.left + box.width / 2 - sceneBox.left, y: box.top + box.height / 2 - sceneBox.top },
        screenCenter: { x: box.left + box.width / 2, y: box.top + box.height / 2 },
      }
    })
    const parseQuadratic = path => {
      const d = path.getAttribute('d') || ''
      const match = d.match(/^\s*M\s*([-\d.]+)[ ,]+([-\d.]+)\s*Q\s*([-\d.]+)[ ,]+([-\d.]+)\s+([-\d.]+)[ ,]+([-\d.]+)\s*$/i)
      if (!match) return { d, start: null, control: null, end: null, screenStart: null, screenControl: null, screenEnd: null }
      const matrix = path.getScreenCTM()
      const transform = (x, y) => {
        const point = new DOMPoint(Number(x), Number(y)).matrixTransform(matrix)
        return { x: point.x, y: point.y }
      }
      return {
        d,
        start: { x: Number(match[1]), y: Number(match[2]) },
        control: { x: Number(match[3]), y: Number(match[4]) },
        end: { x: Number(match[5]), y: Number(match[6]) },
        screenStart: transform(match[1], match[2]),
        screenControl: transform(match[3], match[4]),
        screenEnd: transform(match[5], match[6]),
      }
    }
    const gradients = [...svg.querySelectorAll('linearGradient[id^="agent-beam-"]')].map(gradient => ({
      id: gradient.id,
      units: gradient.getAttribute('gradientUnits'),
      start: { x: Number(gradient.getAttribute('x1')), y: Number(gradient.getAttribute('y1')) },
      end: { x: Number(gradient.getAttribute('x2')), y: Number(gradient.getAttribute('y2')) },
    }))
    return {
      scene: { width: sceneBox.width, height: sceneBox.height },
      coreRect: { left: coreBox.left - sceneBox.left, top: coreBox.top - sceneBox.top, right: coreBox.right - sceneBox.left, bottom: coreBox.bottom - sceneBox.top },
      coreCenter: { x: coreBox.left + coreBox.width / 2 - sceneBox.left, y: coreBox.top + coreBox.height / 2 - sceneBox.top },
      coreScreenCenter,
      svgScreenRect: { left: svgBox.left, top: svgBox.top, width: svgBox.width, height: svgBox.height },
      roles,
      paths: [...element.querySelectorAll('.agent-connection')].map(parseQuadratic),
      gradients,
      pathStrokes: [...element.querySelectorAll('.agent-connection')].map(path => path.getAttribute('stroke')),
    }
  })
}

function assertAgentOrbitGeometry(metrics, label, { noOverlap = false, lineScale = 1 } = {}) {
  assert.equal(metrics.roles.length, 5, `${label}: the orbit should contain five Agent cards`)
  assert.equal(metrics.paths.length, 5, `${label}: the orbit should contain five connections`)
  assert.ok(metrics.scene.width > 0 && metrics.scene.height > 0, `${label}: the Agent scene should have measurable dimensions`)
  const centerX = metrics.scene.width / 2
  const centerY = metrics.scene.height / 2
  assert.ok(Math.abs(metrics.coreCenter.x - centerX) <= metrics.scene.width * 0.025, `${label}: the workflow core should stay horizontally centered`)
  assert.ok(Math.abs(metrics.coreCenter.y - centerY) <= metrics.scene.height * 0.035, `${label}: the workflow core should stay vertically centered`)

  const vectors = metrics.roles.map(role => ({ x: role.center.x - metrics.coreCenter.x, y: role.center.y - metrics.coreCenter.y }))
  const radii = vectors.map(vector => Math.hypot(vector.x, vector.y))
  const meanRadius = radii.reduce((sum, radius) => sum + radius, 0) / radii.length
  const radiusTolerance = Math.max(3, meanRadius * 0.035)
  for (const [index, radius] of radii.entries()) assert.ok(Math.abs(radius - meanRadius) <= radiusTolerance, `${label}: Agent ${index + 1} should share the same orbit radius (${radius.toFixed(1)} vs ${meanRadius.toFixed(1)} px)`)
  const roleAngles = vectors.map(vector => (Math.atan2(vector.y, vector.x) * 180 / Math.PI + 360) % 360)
  const expectedRoleAngles = [198, 270, 342, 54, 126]
  for (const [index, angle] of roleAngles.entries()) {
    const difference = Math.abs(((angle - expectedRoleAngles[index] + 540) % 360) - 180)
    assert.ok(difference <= 4, `${label}: Agent ${index + 1} should keep its assigned position after the one-step counterclockwise rotation; expected ${expectedRoleAngles[index]}°, observed ${angle.toFixed(2)}°`)
  }
  const angles = vectors.map(vector => (Math.atan2(vector.y, vector.x) * 180 / Math.PI + 360) % 360).sort((a, b) => a - b)
  const gaps = angles.map((angle, index) => (angles[(index + 1) % angles.length] + (index === angles.length - 1 ? 360 : 0)) - angle)
  for (const [index, gap] of gaps.entries()) assert.ok(Math.abs(gap - 72) <= 3, `${label}: orbit gap ${index + 1} should be 72° ±3°; observed ${gap.toFixed(2)}°`)

  const symmetryTolerance = Math.max(3, meanRadius * 0.035)
  const axisRoles = vectors.filter(vector => Math.abs(vector.x) <= symmetryTolerance)
  assert.equal(axisRoles.length, 1, `${label}: one Agent should sit on the mirror axis`)
  const unmatched = new Set(vectors.map((_, index) => index).filter(index => Math.abs(vectors[index].x) > symmetryTolerance))
  while (unmatched.size) {
    const index = unmatched.values().next().value
    unmatched.delete(index)
    const mirror = [...unmatched].find(other => Math.abs(vectors[index].x + vectors[other].x) <= symmetryTolerance && Math.abs(vectors[index].y - vectors[other].y) <= symmetryTolerance)
    assert.notEqual(mirror, undefined, `${label}: Agent ${index + 1} should have a mirrored partner across the core`)
    unmatched.delete(mirror)
  }

  for (const role of metrics.roles) {
    assert.ok(role.rect.left >= -1 && role.rect.top >= -1 && role.rect.right <= metrics.scene.width + 1 && role.rect.bottom <= metrics.scene.height + 1, `${label}: ${role.label} should fit inside the Agent scene`)
  }

  const visibleSideLines = []
  if (noOverlap) {
    const intersects = (left, right) => left.left < right.right - 1 && left.right > right.left + 1 && left.top < right.bottom - 1 && left.bottom > right.top + 1
    for (const [index, role] of metrics.roles.entries()) {
      assert.equal(intersects(role.rect, metrics.coreRect), false, `${label}: ${role.label} should not overlap the workflow core`)
      for (const other of metrics.roles.slice(index + 1)) assert.equal(intersects(role.rect, other.rect), false, `${label}: Agent cards should not overlap`)
    }
    for (const index of [0, 2]) {
      const role = metrics.roles[index]
      const vector = vectors[index]
      const radius = radii[index]
      const unitX = Math.abs(vector.x) / radius
      const unitY = Math.abs(vector.y) / radius
      const cardHalfExtent = Math.min(role.rect.width / (2 * unitX), role.rect.height / (2 * unitY))
      const coreWidth = metrics.coreRect.right - metrics.coreRect.left
      const visibleLine = radius - coreWidth / 2 - cardHalfExtent
      assert.ok(visibleLine >= 40, `${label}: ${role.label} should retain at least 40 px of visible connection beyond the core and card; observed ${visibleLine.toFixed(2)} px`)
      visibleSideLines.push({ role: role.label, visiblePx: Number(visibleLine.toFixed(2)) })
    }
  }

  const parseTolerance = 2
  assert.ok(metrics.paths.every(path => path.start && path.control && path.end), `${label}: every connection should use the shared quadratic curve shape`)
  assert.equal(metrics.gradients.length, 5, `${label}: each Agent connection should have its own user-space gradient`)
  assert.equal(metrics.pathStrokes.length, 5)
  assert.ok(Math.abs(metrics.gradients[1]?.end.x - metrics.gradients[1]?.start.x) <= 0.01, `${label}: the vertical planning spoke should retain a zero-width gradient vector`)
  assert.ok(Math.abs(metrics.gradients[1]?.end.y - metrics.gradients[1]?.start.y) > 1, `${label}: the vertical planning gradient should remain valid along its nonzero height`)
  for (const [index, path] of metrics.paths.entries()) {
    const expectedId = `agent-beam-${index}`
    const gradient = metrics.gradients.find(item => item.id === expectedId)
    assert.ok(gradient, `${label}: gradient ${expectedId} should exist`)
    assert.equal(gradient.units, 'userSpaceOnUse', `${label}: ${expectedId} must use userSpaceOnUse coordinates`)
    assert.equal(metrics.pathStrokes[index], `url(#${expectedId})`, `${label}: connection ${index + 1} should reference its matching gradient`)
    assert.ok(Math.hypot(gradient.start.x - path.start.x, gradient.start.y - path.start.y) <= 0.01, `${label}: ${expectedId} should begin at its own connection start`)
    assert.ok(Math.hypot(gradient.end.x - path.end.x, gradient.end.y - path.end.y) <= 0.01, `${label}: ${expectedId} should end at its own connection endpoint`)
    assert.ok(Math.hypot(gradient.end.x - gradient.start.x, gradient.end.y - gradient.start.y) > 1, `${label}: ${expectedId} must remain non-degenerate`)
    assert.ok(Math.hypot(path.screenStart.x - metrics.coreScreenCenter.x, path.screenStart.y - metrics.coreScreenCenter.y) <= parseTolerance, `${label}: connection ${index + 1} should start at the core center after SVG transforms`)
    const target = metrics.roles[index].screenCenter
    const targetVector = { x: target.x - metrics.coreScreenCenter.x, y: target.y - metrics.coreScreenCenter.y }
    const endpointVector = { x: path.screenEnd.x - metrics.coreScreenCenter.x, y: path.screenEnd.y - metrics.coreScreenCenter.y }
    const endpointRatio = Math.hypot(endpointVector.x, endpointVector.y) / Math.hypot(targetVector.x, targetVector.y)
    const angleError = Math.abs(Math.atan2(targetVector.x * endpointVector.y - targetVector.y * endpointVector.x, targetVector.x * endpointVector.x + targetVector.y * endpointVector.y)) * 180 / Math.PI
    assert.ok(Math.abs(endpointRatio - lineScale) <= 0.025, `${label}: connection ${index + 1} should end at the shared ${lineScale} orbit scale; observed ${endpointRatio.toFixed(3)}`)
    assert.ok(angleError <= 1.5, `${label}: connection ${index + 1} should point toward its Agent card; angle error ${angleError.toFixed(2)}°`)
  }
  const start = metrics.paths[0].screenStart
  for (const path of metrics.paths.slice(1)) assert.ok(Math.hypot(path.screenStart.x - start.x, path.screenStart.y - start.y) <= parseTolerance, `${label}: all connections should share one generated start point`)
  const curvature = metrics.paths.map(path => {
    const dx = path.screenEnd.x - path.screenStart.x
    const dy = path.screenEnd.y - path.screenStart.y
    const length = Math.hypot(dx, dy)
    const midpoint = { x: (path.screenStart.x + path.screenEnd.x) / 2, y: (path.screenStart.y + path.screenEnd.y) / 2 }
    const offset = { x: path.screenControl.x - midpoint.x, y: path.screenControl.y - midpoint.y }
    return { normal: (offset.x * -dy + offset.y * dx) / (length * length), tangent: (offset.x * dx + offset.y * dy) / (length * length) }
  })
  assert.ok(curvature.every(curve => Math.abs(curve.tangent) <= 0.025), `${label}: shared curve controls should stay perpendicular to their chords`)
  assert.ok(Math.max(...curvature.map(curve => curve.normal)) - Math.min(...curvature.map(curve => curve.normal)) <= 0.025, `${label}: every connection should use the same relative arc curvature`)
  return { radiiPx: radii.map(radius => Number(radius.toFixed(2))), anglesDeg: angles.map(angle => Number(angle.toFixed(2))), gapsDeg: gaps.map(gap => Number(gap.toFixed(2))), symmetryPairs: vectors.map(vector => ({ x: Number(vector.x.toFixed(2)), y: Number(vector.y.toFixed(2)) })), visibleSideLines, curvature, gradientContract: metrics.gradients }
}

function assertAgentSelectionInvariant(frame, label) {
  assert.equal(frame.selectedIndices.length, 1, `${label}: exactly one Agent role must be selected`)
  assert.equal(frame.activeConnectionIndices.length, 1, `${label}: exactly one corresponding connection must be selected`)
  assert.equal(frame.activeConnectionIndices[0], frame.selectedIndices[0], `${label}: selected role and connection must match`)
}

function assertAgentVisualTransition(before, after, index, label) {
  assertAgentSelectionInvariant(after, label)
  assert.equal(after.selectedIndices[0], index, `${label}: expected role ${index} to be selected`)
  const fields = ['backgroundColor', 'borderColor', 'boxShadow', 'iconColor', 'textColor']
  for (const field of fields) assert.notEqual(after.roles[index][field], before.roles[index][field], `${label}: entering role ${index} should change ${field}`)
  assert.notEqual(after.connections[index].opacity, before.connections[index].opacity, `${label}: entering connection ${index} should change opacity`)
  assert.notEqual(after.connections[index].strokeWidth, before.connections[index].strokeWidth, `${label}: entering connection ${index} should change stroke width`)
  const other = (index + 1) % after.roles.length
  for (const field of fields) assert.notEqual(after.roles[index][field], after.roles[other][field], `${label}: selected and unselected roles should differ in ${field}`)
  assert.notEqual(after.connections[index].opacity, after.connections[other].opacity, `${label}: selected and unselected connections should differ in opacity`)
  assert.notEqual(after.connections[index].strokeWidth, after.connections[other].strokeWidth, `${label}: selected and unselected connections should differ in stroke width`)
}

async function settleAgentRoleTransition(locator) {
  await locator.evaluate(async element => {
    const transitions = element.getAnimations()
    if (transitions.length) await Promise.all(transitions.map(animation => animation.finished.catch(() => undefined)))
  })
}

async function waitForSection(page, id) {
  await page.waitForFunction(sectionId => {
    const scroller = document.querySelector('.landing-main')
    const screen = document.getElementById(sectionId)
    return location.hash === '#' + sectionId && scroller && screen && Math.abs(scroller.scrollTop - screen.offsetTop) < 4
  }, id)
  await waitForVisualStability(page)
}

async function verifyNavigationAndHistory(page) {
  const labels = page.locator('.screen-pagination button')
  assert.equal(await labels.count(), 6, 'Screen pagination should contain six controls')
  for (let index = 0; index < screenLabels.length; index++) {
    assert.equal(await labels.nth(index).getAttribute('aria-label'), '第 ' + (index + 1) + ' 屏：' + screenLabels[index])
  }
  await page.goto(base + '/#features', { waitUntil: 'networkidle' })
  await waitForSection(page, 'features')
  const cards = page.locator('#features .feature-card')
  assert.equal(await cards.count(), 4, 'Platform capability screen should contain four feature anchors')
  for (let index = 0; index < features.length; index++) {
    const card = cards.nth(index)
    assert.equal(await card.evaluate(el => el.tagName), 'A', 'Feature card should be a native anchor')
    assert.equal(await card.getAttribute('href'), '#' + features[index].id, 'Feature card should link to its homepage section')
  }
  await cards.nth(1).click()
  await page.waitForURL(routeUrl(features[1]))
  await assertFeature(page, features[1])
  await page.goBack({ waitUntil: 'networkidle' })
  await page.waitForURL(base + '/#features')
  await waitForSection(page, 'features')
  await page.goForward({ waitUntil: 'networkidle' })
  await page.waitForURL(routeUrl(features[1]))
  await assertFeature(page, features[1])
  evidence.routes.push({ cards: features.map(feature => ({ href: '#' + feature.id, hash: feature.id })), backForward: 'PASS' })
}

async function verifyMotionPreference(page, feature) {
  const motionControlSelector = {
    agents: '.agent-role',
    evidence: '.claim-rule-options button',
    path: '.journey-step',
    feedback: '.feedback-training',
  }[feature.key]
  if (feature.key === 'agents') await installShowcaseTimerProbe(page, '#multi-agent .agent-constellation', 'showcase')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.reload({ waitUntil: 'networkidle' })
  const panel = await assertFeature(page, feature)
  const normalMotion = await panel.locator('.feature-scene').evaluate(el => {
    const style = getComputedStyle(el)
    return { animationName: style.animationName, animationDuration: style.animationDuration }
  })
  normalMotion.transitionDuration = await panel.locator(motionControlSelector).first().evaluate(el => getComputedStyle(el).transitionDuration)
  assert.notEqual(normalMotion.animationName, 'none', feature.id + ': normal entrance motion must remain enabled')
  assert.ok(normalMotion.animationDuration.split(',').some(duration => Number.parseFloat(duration) > 0), feature.id + ': normal motion should have a finite nonzero duration')
  if (feature.key !== 'evidence') assert.ok(normalMotion.transitionDuration.split(',').some(duration => Number.parseFloat(duration) > 0), feature.id + ': normal interactive transitions must remain enabled')

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.reload({ waitUntil: 'networkidle' })
  const reducedPanel = await assertFeature(page, feature)
  const motionState = await page.locator('.landing-page').evaluate(root => ({
    running: root.getAnimations({ subtree: true })
      .filter(animation => animation.playState === 'running')
      .map(animation => ({ name: animation.animationName || animation.constructor.name, duration: animation.effect?.getTiming().duration })),
    animationName: getComputedStyle(root.querySelector('.showcase-panel.is-active .feature-scene') || root.querySelector('#' + location.hash.slice(1) + ' .feature-scene')).animationName,
    transitionDuration: null,
  }))
  motionState.transitionDuration = await reducedPanel.locator(motionControlSelector).first().evaluate(el => getComputedStyle(el).transitionDuration)
  const running = motionState.running
  assert.deepEqual(running, [], feature.id + ': automatic entrance/motion continues under reduced-motion preference')
  assert.equal(motionState.animationName, 'none', feature.id + ': reduced motion should disable entrance animations')
  assert.ok(motionState.transitionDuration.split(',').every(duration => Number.parseFloat(duration) === 0), feature.id + ': reduced motion should disable transitions')

  if (feature.key === 'agents') {
    const beforeStaticRun = await page.evaluate(() => window.__agentTimerProbe())
    await reducedPanel.getByRole('button', { name: '演示一次协作', exact: true }).click()
    assert.match(await reducedPanel.getByRole('status').innerText(), /协作示意完成/)
    assert.equal(await reducedPanel.getByRole('button', { name: '查看Claim智能体', exact: true }).getAttribute('aria-pressed'), 'true')
    assert.equal(await reducedPanel.getByRole('button', { name: '暂停演示', exact: true }).count(), 0, 'Reduced-motion demo should complete without a pause state')
    const staticFrame = await readAgentVisualFrame(reducedPanel.locator('.agent-constellation'))
    assert.equal(staticFrame.complete, true, 'Reduced-motion Agent demo should expose the complete static state')
    assertAgentSelectionInvariant(staticFrame, 'Reduced-motion Agent state')
    assert.equal(staticFrame.selectedIndices[0], 4)
    const afterStaticRun = await page.evaluate(() => window.__agentTimerProbe())
    const newAgentTimers = afterStaticRun.scheduled.filter(timer => timer.delay === 1800).length - beforeStaticRun.scheduled.filter(timer => timer.delay === 1800).length
    assert.equal(newAgentTimers, 0, 'Reduced-motion Agent demo should complete without scheduling an 1800 ms timer')
  } else if (feature.key === 'feedback') {
    const workbench = reducedPanel.locator('.feedback-workbench')
    assert.equal(await workbench.getAttribute('data-playing'), 'false', 'Reduced-motion feedback should remain static')
    assert.ok((await workbench.getAttribute('class')).includes('is-static'), 'Reduced-motion feedback should expose its static route treatment')
    assert.equal(await reducedPanel.locator('.feedback-playback').count(), 0, 'Reduced-motion feedback should not offer a playback control')
    assert.equal(await reducedPanel.locator('.feedback-stage').count(), 3, 'Static feedback should keep all three semantic stages visible')
    assert.equal(await reducedPanel.locator('.feedback-status').innerText(), '减少动态效果 · 三步静态展示')
  }
  evidence.motionChecks.push({ feature: feature.key, normalMotion: normalMotion.animationName, reducedMotion: 'no running animations or transitions' })
}

async function installShowcaseTimerProbe(page, selector = '#feedback-loop .feedback-workbench', timerKind = 'feedback') {
  await page.addInitScript(({ selector, timerKind }) => {
    const nativeSetTimeout = window.setTimeout.bind(window)
    const nativeClearTimeout = window.clearTimeout.bind(window)
    const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window)
    const nativeCancelAnimationFrame = window.cancelAnimationFrame.bind(window)
    const active = new Map()
    const scheduled = []
    const fired = []
    const cleared = []
    const activeFrames = new Map()
    const scheduledFrames = []
    const firedFrames = []
    const cancelledFrames = []
    const phaseEvents = []
    const agentEvents = []
    const documentListeners = new Set()
    const motionListeners = new Set()
    const activeResizeObservers = new Set()
    const NativeResizeObserver = window.ResizeObserver
    window.ResizeObserver = class extends NativeResizeObserver {
      constructor(callback) { super(callback); activeResizeObservers.add(this) }
      disconnect() { activeResizeObservers.delete(this); return super.disconnect() }
    }
    const readPhase = workbench => ({
      phase: Number(workbench.dataset.phase),
      cycle: workbench.dataset.cycle === undefined ? null : Number(workbench.dataset.cycle),
      playing: workbench.dataset.playing === 'true',
      rule: workbench.dataset.rule || workbench.dataset.verdict || null,
      verdictReady: workbench.dataset.verdictReady === 'true',
      verdictProgress: Number(workbench.dataset.verdictProgress || 0),
      at: performance.now(),
    })
    let observedWorkbench = null
    let phaseObserver = null
    const attachPhaseObserver = () => {
      const workbench = document.querySelector(selector)
      if (!workbench) {
        phaseObserver?.disconnect()
        phaseObserver = null
        observedWorkbench = null
        return
      }
      if (!workbench || workbench === observedWorkbench) return
      phaseObserver?.disconnect()
      observedWorkbench = workbench
      phaseEvents.push(readPhase(workbench))
      phaseObserver = new MutationObserver(() => {
        const next = readPhase(workbench)
        const last = phaseEvents.at(-1)
        if (!last || ['phase', 'cycle', 'playing', 'rule', 'verdictReady'].some(key => last[key] !== next[key])) phaseEvents.push(next)
      })
      phaseObserver.observe(workbench, { attributes: true, attributeFilter: ['data-phase', 'data-cycle', 'data-playing', 'data-rule', 'data-verdict', 'data-verdict-ready'] })
    }
    const readAgent = scene => {
      const roles = [...scene.querySelectorAll('.agent-role')]
      const connections = [...scene.querySelectorAll('.agent-connection')]
      return {
        selectedIndices: roles.flatMap((role, index) => role.getAttribute('aria-pressed') === 'true' ? [index] : []),
        activeConnectionIndices: connections.flatMap((connection, index) => connection.classList.contains('is-active') ? [index] : []),
        running: scene.classList.contains('is-running'),
        complete: scene.classList.contains('is-complete'),
        status: scene.querySelector('[role="status"]')?.innerText.trim() || '',
        at: performance.now(),
      }
    }
    let observedAgentScene = null
    let agentObserver = null
    let lastAgentSignature = null
    const attachAgentObserver = () => {
      const scene = document.querySelector('#multi-agent .agent-constellation')
      if (!scene) {
        agentObserver?.disconnect()
        agentObserver = null
        observedAgentScene = null
        lastAgentSignature = null
        return
      }
      if (scene === observedAgentScene) return
      agentObserver?.disconnect()
      observedAgentScene = scene
      const capture = () => {
        const next = readAgent(scene)
        const signature = JSON.stringify({ ...next, at: undefined })
        if (signature === lastAgentSignature) return
        lastAgentSignature = signature
        agentEvents.push(next)
      }
      capture()
      agentObserver = new MutationObserver(capture)
      agentObserver.observe(scene, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class', 'aria-pressed'] })
    }
    const attachObservers = () => { attachPhaseObserver(); attachAgentObserver() }
    const documentObserver = new MutationObserver(attachObservers)
    documentObserver.observe(document, { childList: true, subtree: true })
    document.addEventListener('DOMContentLoaded', attachObservers, { once: true })
    attachObservers()

    window.setTimeout = (handler, delay, ...args) => {
      const actualDelay = Number(delay)
      // LandingView's wheelIdleTimer is 180 ms and is deliberately outside this probe.
      const agentSceneRunning = document.querySelector('#multi-agent .agent-constellation')?.classList.contains('is-running') === true
      const agentPanelActive = document.querySelector('#multi-agent.showcase-panel.is-active') !== null
      const handlerCaller = actualDelay === 1800 ? (new Error()).stack?.split('\n').slice(1, 4).join(' <- ') || '' : ''
      const handlerName = typeof handler === 'function' ? handler.name : ''
      // Attribute 1800 ms timers by the active feature panel. Vue can schedule the
      // first Agent timeout before its is-running class has reached the DOM, while
      // Evidence uses the same duration on a different, inactive panel.
      const trackAgent = actualDelay === 1800 && agentPanelActive
      const trackShowcase = actualDelay >= 1000 && actualDelay <= 6000
      if (!trackAgent && !trackShowcase) return nativeSetTimeout(handler, delay, ...args)
      const entry = { delay: actualDelay, kind: trackAgent ? 'agent' : timerKind, agentPanelActiveAtSchedule: agentPanelActive, agentSceneRunningAtSchedule: agentSceneRunning, handlerName, handlerCaller, scheduledAt: performance.now() }
      let id
      const wrapped = typeof handler === 'function' ? function (...callbackArgs) {
        active.delete(id)
        fired.push({ ...entry, firedAt: performance.now() })
        return handler.apply(this, callbackArgs)
      } : handler
      id = nativeSetTimeout(wrapped, delay, ...args)
      entry.id = String(id)
      scheduled.push(entry)
      active.set(id, entry)
      return id
    }
    window.clearTimeout = id => {
      const entry = active.get(id)
      if (entry) {
        active.delete(id)
        cleared.push({ ...entry, clearedAt: performance.now() })
      }
      return nativeClearTimeout(id)
    }
    window.requestAnimationFrame = callback => {
      const entry = { scheduledAt: performance.now() }
      let id
      id = nativeRequestAnimationFrame(timestamp => {
        activeFrames.delete(id)
        firedFrames.push({ ...entry, id: String(id), firedAt: performance.now() })
        callback(timestamp)
      })
      entry.id = String(id)
      scheduledFrames.push(entry)
      activeFrames.set(id, entry)
      return id
    }
    window.cancelAnimationFrame = id => {
      const entry = activeFrames.get(id)
      if (entry) {
        activeFrames.delete(id)
        cancelledFrames.push({ ...entry, cancelledAt: performance.now() })
      }
      return nativeCancelAnimationFrame(id)
    }

    const nativeDocumentAdd = document.addEventListener.bind(document)
    const nativeDocumentRemove = document.removeEventListener.bind(document)
    document.addEventListener = (type, listener, ...rest) => {
      if (type === 'visibilitychange') documentListeners.add(listener)
      return nativeDocumentAdd(type, listener, ...rest)
    }
    document.removeEventListener = (type, listener, ...rest) => {
      if (type === 'visibilitychange') documentListeners.delete(listener)
      return nativeDocumentRemove(type, listener, ...rest)
    }
    const nativeMatchMedia = window.matchMedia.bind(window)
    window.matchMedia = query => {
      const media = nativeMatchMedia(query)
      if (query === '(prefers-reduced-motion: reduce)') {
        const nativeAdd = media.addEventListener.bind(media)
        const nativeRemove = media.removeEventListener.bind(media)
        media.addEventListener = (type, listener, ...rest) => {
          if (type === 'change') motionListeners.add(listener)
          return nativeAdd(type, listener, ...rest)
        }
        media.removeEventListener = (type, listener, ...rest) => {
          if (type === 'change') motionListeners.delete(listener)
          return nativeRemove(type, listener, ...rest)
        }
      }
      return media
    }
    const readProbe = () => ({
      scheduled: [...scheduled], fired: [...fired], cleared: [...cleared],
      active: [...active.values()].map(entry => ({ ...entry })),
      raf: {
        scheduled: [...scheduledFrames], fired: [...firedFrames], cancelled: [...cancelledFrames],
        active: [...activeFrames.values()].map(entry => ({ ...entry })),
      },
      phaseEvents: [...phaseEvents],
      agentEvents: [...agentEvents],
      visibilityListeners: documentListeners.size,
      motionListeners: motionListeners.size,
      resizeObservers: activeResizeObservers.size,
    })
    window.__feedbackTimerProbe = readProbe
    window.__evidenceTimerProbe = readProbe
    window.__agentTimerProbe = readProbe
  }, { selector, timerKind })
}

async function readFeedbackVisualFrame(workbench) {
  return workbench.evaluate(element => {
    const path = element.querySelector('.feedback-turn-line')
    const marker = element.querySelector('.feedback-flow-marker')
    const bar = element.querySelector('.feedback-progress > span.is-current > i')
    const transform = marker?.getAttribute('transform') || ''
    const markerPoint = transform.match(/translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)/)
    const totalLength = path?.getTotalLength() || 0
    const routeProgress = Number(element.dataset.routeProgress)
    const expected = path?.getPointAtLength(totalLength * routeProgress)
    const barTransform = bar ? new DOMMatrixReadOnly(getComputedStyle(bar).transform) : null
    return {
      phase: Number(element.dataset.phase),
      cycle: Number(element.dataset.cycle),
      rule: element.dataset.rule,
      playing: element.dataset.playing,
      routeProgress,
      phaseProgress: Number(element.dataset.phaseProgress),
      path: path?.getAttribute('d') || '',
      moveCount: (path?.getAttribute('d')?.match(/[Mm]/g) || []).length,
      marker: markerPoint ? { x: Number(markerPoint[1]), y: Number(markerPoint[2]) } : null,
      expected: expected ? { x: expected.x, y: expected.y } : null,
      dashOffset: Number(path?.style.strokeDashoffset),
      barProgress: barTransform?.a ?? null,
      markerOpacity: Number(getComputedStyle(marker).opacity),
      pathLength: totalLength,
    }
  })
}

async function readFeedbackRouteEmphasis(workbench) {
  return workbench.evaluate(element => {
    const style = selector => {
      const node = element.querySelector(selector)
      const computed = getComputedStyle(node)
      return {
        color: computed.color,
        backgroundColor: computed.backgroundColor,
        backgroundImage: computed.backgroundImage,
        borderColor: computed.borderColor,
        boxShadow: computed.boxShadow,
      }
    }
    return {
      phase: Number(element.dataset.phase),
      routeBody: style('.route-body'),
      routeCard: style('.feedback-adjusted-route > li'),
      nodeLetter: style('.feedback-adjusted-route > li .node-letter'),
      routeState: style('.route-state'),
      routeLineOpacity: Number(getComputedStyle(element.querySelector('.feedback-turn-line')).opacity),
      markerOpacity: Number(getComputedStyle(element.querySelector('.feedback-flow-marker')).opacity),
      turningPointFill: getComputedStyle(element.querySelector('.feedback-turn-point')).fill,
    }
  })
}

function assertFeedbackVisualFrame(frame, label) {
  assert.equal(frame.moveCount, 1, `${label}: the feedback route must be one continuous SVG subpath`)
  assert.ok(frame.marker && frame.expected, `${label}: route marker and path point should be measurable`)
  assert.ok(Math.hypot(frame.marker.x - frame.expected.x, frame.marker.y - frame.expected.y) <= 0.03, `${label}: marker must use the shared route progress; ${JSON.stringify(frame)}`)
  assert.ok(Math.abs(frame.dashOffset - (1 - frame.routeProgress)) <= 0.00002, `${label}: route stroke should use the shared route progress`)
  assert.ok(Math.abs(frame.barProgress - frame.phaseProgress) <= 0.025, `${label}: phase bar and data-phase-progress should agree`)
}

async function focusFeedbackByKeyboard(page, panel, locator, label) {
  await page.locator('#feedback-title').focus()
  for (let index = 0; index < 32; index++) {
    await page.keyboard.press('Tab')
    if (await locator.evaluate(element => element === document.activeElement)) {
      assert.equal(await locator.evaluate(element => element.matches(':focus-visible')), true, `${label}: Tab focus must use keyboard modality`)
      return
    }
  }
  throw new Error(`${label}: keyboard Tab sequence did not reach the feedback control`)
}

async function setScreenImmediately(page, id) {
  await page.evaluate(sectionId => {
    const scroller = document.querySelector('.landing-main')
    const target = document.getElementById(sectionId)
    scroller.scrollTop = target.offsetTop
    scroller.dispatchEvent(new Event('scroll'))
  }, id)
  await page.waitForFunction(sectionId => {
    const scroller = document.querySelector('.landing-main')
    const target = document.getElementById(sectionId)
    return scroller && target && Math.abs(scroller.scrollTop - target.offsetTop) < 2
  }, id)
}

async function verifyDemoTimerStops(page, feature, otherFeature) {
  await installShowcaseTimerProbe(page, '#multi-agent .agent-constellation', 'showcase')
  const panel = await openFeature(page, feature)
  assert.equal(await panel.evaluate(element => element.classList.contains('is-active')), true, 'Agent timer probe should start with its showcase panel active')
  const readLocalState = async () => ({
    heading: (await panel.locator('[data-role-panel] h3').innerText()).trim(),
    selectedRoles: (await panel.locator('button[aria-pressed="true"]').allTextContents()).map(text => text.trim()),
  })
  const readProbe = () => page.evaluate(() => window.__agentTimerProbe())
  const activeAgentTimers = probe => probe.active.filter(timer => timer.kind === 'agent')
  await panel.getByRole('button', { name: '演示一次协作', exact: true }).click()
  await panel.getByRole('button', { name: '暂停演示', exact: true }).waitFor({ state: 'visible' })
  const started = await readProbe()
  const firstAgentTimer = started.scheduled.find(timer => timer.kind === 'agent')
  assert.ok(firstAgentTimer, feature.key + ' demo should schedule an Agent-owned timer; observed timers: ' + JSON.stringify(started.scheduled.map(({ delay, kind, agentPanelActiveAtSchedule, handlerName, handlerCaller }) => ({ delay, kind, agentPanelActiveAtSchedule, handlerName, handlerCaller }))))
  assert.equal(firstAgentTimer.delay, feature.delay, feature.key + ' Agent timer should use the declared 1800 ms interval')
  assert.equal(firstAgentTimer.agentPanelActiveAtSchedule, true, 'Timer ownership should be attributed to the active Agent showcase panel')
  assert.ok(firstAgentTimer.handlerCaller, 'Timer ownership evidence should retain the scheduling caller')
  assert.equal(activeAgentTimers(started).length, 1, feature.key + ' should have one Agent timer active before advancing')

  const planner = panel.getByRole('button', { name: '查看规划智能体', exact: true })
  await planner.waitFor({ state: 'visible' })
  await page.waitForFunction(() => document.querySelector('#multi-agent .agent-role[aria-label="查看规划智能体"]')?.getAttribute('aria-pressed') === 'true')
  await panel.getByRole('button', { name: '暂停演示', exact: true }).click()
  const paused = await readProbe()
  assert.equal(activeAgentTimers(paused).length, 0, 'Pausing the Agent demo should clear its scheduled timer')
  const localStateAtPause = await readLocalState()
  assert.match(localStateAtPause.heading, /规划 Agent/)
  const firedAtPause = paused.fired.filter(timer => timer.kind === 'agent').length
  await page.waitForTimeout(350)
  const held = await readProbe()
  assert.equal(held.fired.filter(timer => timer.kind === 'agent').length, firedAtPause, 'Pause should prevent the next Agent callback from firing')
  assert.deepEqual(await readLocalState(), localStateAtPause, 'Pause should keep the current Agent role selected')

  await panel.getByRole('button', { name: '继续演示', exact: true }).click()
  await page.waitForFunction(() => window.__agentTimerProbe().active.some(timer => timer.kind === 'agent'))
  const resumed = await readProbe()
  assert.equal(activeAgentTimers(resumed).length, 1, 'Continue should schedule one Agent timer')
  assert.equal(activeAgentTimers(resumed)[0].delay, feature.delay)
  assert.equal(activeAgentTimers(resumed)[0].agentPanelActiveAtSchedule, true)
  assert.deepEqual(await readLocalState(), localStateAtPause, 'Continue should resume from the selected planner role')
  const beforeLeave = await readLocalState()

  await setScreenImmediately(page, otherFeature.id)
  await page.waitForFunction(() => window.__agentTimerProbe().active.every(timer => timer.kind !== 'agent'), null, { timeout: 1000 })
  const stopped = await readProbe()
  assert.equal(activeAgentTimers(stopped).length, 0, 'Leaving the Agent screen should clear its timer')
  await page.waitForTimeout(feature.delay + 100)

  const afterDelay = await readLocalState()
  assert.deepEqual(afterDelay, beforeLeave, feature.key + ' local state should remain unchanged after its off-screen timer stops')

  await setScreenImmediately(page, feature.id)
  await waitForSection(page, feature.id)
  await assertFeature(page, feature)
  const afterReturn = await readLocalState()
  assert.deepEqual(afterReturn, beforeLeave, feature.key + ' local state should be preserved when re-entering the screen')
  evidence.agentLifecycleChecks.push({
    pause: { selectedRole: localStateAtPause.heading, activeTimersAfterPause: activeAgentTimers(paused).length, waitedMs: 350, callbacksAfterPause: held.fired.filter(timer => timer.kind === 'agent').length - firedAtPause },
    continue: { activeTimers: activeAgentTimers(resumed).length, selectedRolePreserved: true },
    offscreen: { activeTimers: activeAgentTimers(stopped).length, selectedRolePreserved: true, waitedAfterLeaveMs: feature.delay + 100 },
    timerOwner: { delay: firstAgentTimer.delay, agentPanelActiveAtSchedule: firstAgentTimer.agentPanelActiveAtSchedule, agentSceneRunningAtSchedule: firstAgentTimer.agentSceneRunningAtSchedule, handlerName: firstAgentTimer.handlerName, handlerCaller: firstAgentTimer.handlerCaller },
  })
  evidence.interactions.push({ feature: feature.key, offScreenTimerCleared: true, localStatePreserved: true })
}

async function verifyAgentAutomaticSequence(page) {
  const feature = features.find(item => item.key === 'agents')
  const labels = ['诊断', '规划', '生成', '审核', 'Claim']
  await installShowcaseTimerProbe(page, '#multi-agent .agent-constellation', 'showcase')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  const panel = await openFeature(page, feature)
  const scene = panel.locator('.agent-constellation')
  const roleButtons = panel.locator('.agent-role')
  const readProbe = () => page.evaluate(() => window.__agentTimerProbe())

  let previousFrame = await readAgentVisualFrame(scene)
  assertAgentSelectionInvariant(previousFrame, 'Agent idle start')
  assert.equal(previousFrame.selectedIndices[0], 0)
  await roleButtons.nth(1).click()
  await page.waitForFunction(() => document.querySelector('#multi-agent .agent-role[aria-label="查看规划智能体"]')?.getAttribute('aria-pressed') === 'true')
  await settleAgentRoleTransition(roleButtons.nth(1))
  const plannerFrame = await readAgentVisualFrame(scene)
  assertAgentVisualTransition(previousFrame, plannerFrame, 1, 'Manual selection of planner')
  previousFrame = plannerFrame
  await roleButtons.nth(0).click()
  await page.waitForFunction(() => document.querySelector('#multi-agent .agent-role[aria-label="查看诊断智能体"]')?.getAttribute('aria-pressed') === 'true')
  await settleAgentRoleTransition(roleButtons.nth(0))
  const resetFrame = await readAgentVisualFrame(scene)
  assertAgentVisualTransition(previousFrame, resetFrame, 0, 'Manual selection back to diagnosis')
  previousFrame = resetFrame

  await panel.getByRole('button', { name: '演示一次协作', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('#multi-agent .agent-constellation')?.classList.contains('is-running'))
  const startedFrame = await readAgentVisualFrame(scene)
  assertAgentSelectionInvariant(startedFrame, 'Agent natural sequence start')
  const roleFrames = []
  for (let index = 1; index < labels.length; index++) {
    const label = labels[index]
    const role = panel.getByRole('button', { name: `查看${label}智能体`, exact: true })
    await page.waitForFunction(expected => document.querySelector(`#multi-agent .agent-role[aria-label="查看${expected}"]`)?.getAttribute('aria-pressed') === 'true', `${label}智能体`)
    await settleAgentRoleTransition(role)
    const frame = await readAgentVisualFrame(scene)
    assertAgentVisualTransition(previousFrame, frame, index, `Natural ${label} selection`)
    assert.equal((await panel.locator('[data-role-panel] h3').innerText()).trim(), `${label} Agent`)
    await contrast(page, panel.locator('.agent-role[aria-pressed="true"] .agent-role-copy strong'), `Agent ${label} selected text`)
    await contrast(page, panel.locator('.agent-role:not([aria-pressed="true"]) .agent-role-copy strong').first(), `Agent ${label} unselected text`)
    roleFrames.push({ role: label, selected: frame.roles[index], unselected: frame.roles[(index + 1) % labels.length], connection: frame.connections[index] })
    previousFrame = frame
  }

  await page.waitForFunction(() => document.querySelector('#multi-agent [role="status"]')?.innerText.includes('协作示意完成'))
  const completeFrame = await readAgentVisualFrame(scene)
  assert.equal(completeFrame.complete, true, 'The final Agent role should remain selected at completion')
  assert.equal(completeFrame.running, false)
  assertAgentSelectionInvariant(completeFrame, 'Agent complete state')
  assert.equal(completeFrame.selectedIndices[0], 4)
  assert.equal(completeFrame.status, '协作示意完成 · Claim 为可选分支')

  const timing = await page.evaluate(() => {
    const probe = window.__agentTimerProbe()
    const startIndex = probe.agentEvents.findIndex(event => event.running && !event.complete && event.selectedIndices.length === 1 && event.selectedIndices[0] === 0)
    const run = probe.agentEvents.slice(startIndex)
    const start = run[0]
    let lastIndex = start?.selectedIndices[0]
    const roleStarts = start ? [start] : []
    let completed
    for (const event of run.slice(1)) {
      if (event.complete) { completed = event; break }
      const selected = event.selectedIndices[0]
      if (event.running && selected !== lastIndex) {
        roleStarts.push(event)
        lastIndex = selected
      }
    }
    const relevantEvents = run.filter(event => completed && event.at <= completed.at)
    const intervals = roleStarts.slice(1).map((event, index) => ({ from: roleStarts[index].selectedIndices[0], to: event.selectedIndices[0], elapsed: event.at - roleStarts[index].at }))
    if (completed && roleStarts.length) intervals.push({ from: roleStarts.at(-1).selectedIndices[0], to: 'complete', elapsed: completed.at - roleStarts.at(-1).at })
    return {
      agentEvents: relevantEvents,
      roleStarts,
      completed,
      intervals,
      totalElapsed: completed && start ? completed.at - start.at : null,
      scheduled: probe.scheduled.filter(timer => timer.kind === 'agent'),
      fired: probe.fired.filter(timer => timer.kind === 'agent'),
    }
  })
  assert.deepEqual(timing.roleStarts.map(event => event.selectedIndices[0]), [0, 1, 2, 3, 4], `The natural Agent sequence should visit all five roles in order: ${JSON.stringify(timing.roleStarts)}`)
  assert.ok(timing.completed?.complete, 'The Agent sequence should emit a complete state')
  for (const [index, event] of timing.agentEvents.entries()) {
    assert.equal(event.selectedIndices.length, 1, `Agent event ${index} should have exactly one selected role`)
    assert.equal(event.activeConnectionIndices.length, 1, `Agent event ${index} should have exactly one selected connection`)
    assert.equal(event.activeConnectionIndices[0], event.selectedIndices[0], `Agent event ${index} should pair the selected role and connection`)
  }
  assert.equal(timing.intervals.length, 5)
  for (const [index, interval] of timing.intervals.entries()) {
    assert.ok(Math.abs(interval.elapsed - feature.delay) <= 700, `Agent step ${index + 1} should last 1800 ms ±700 ms; observed ${interval.elapsed.toFixed(0)} ms`)
  }
  assert.ok(timing.totalElapsed >= 8500 && timing.totalElapsed <= 10500, `Five Agent steps should take about 9 seconds; observed ${timing.totalElapsed?.toFixed(0)} ms`)
  assert.equal(timing.scheduled.length, 5, 'The complete Agent run should schedule five real timers')
  assert.deepEqual(timing.scheduled.map(timer => timer.delay), Array(5).fill(feature.delay))
  assert.ok(timing.scheduled.every(timer => timer.agentPanelActiveAtSchedule && timer.handlerCaller), 'Each 1800 ms Agent timer should be attributed to the active Agent panel and retain its caller')
  assert.equal(timing.fired.length, 5, 'The complete Agent run should fire all five real timers')
  for (const timer of timing.fired) assert.ok(Math.abs(timer.firedAt - timer.scheduledAt - feature.delay) <= 700, `The Agent ${feature.delay} ms timer should not be accelerated`)
  evidence.agentTimingChecks.push({
    roles: labels,
    intervalMs: feature.delay,
    transitions: timing.intervals.map(item => ({ ...item, elapsed: Math.round(item.elapsed) })),
    totalElapsedMs: Math.round(timing.totalElapsed),
    timerOwnership: timing.scheduled.map(timer => ({ delay: timer.delay, agentPanelActiveAtSchedule: timer.agentPanelActiveAtSchedule, agentSceneRunningAtSchedule: timer.agentSceneRunningAtSchedule, handlerName: timer.handlerName, handlerCaller: timer.handlerCaller })),
    selectedRoleFrames: roleFrames,
    completeFrame,
  })
}

async function verifyFeedbackAutomaticLoop(page) {
  const feature = features.find(item => item.key === 'feedback')
  await installShowcaseTimerProbe(page)
  await page.goto(routeUrl(feature), { waitUntil: 'networkidle' })
  const panel = await assertFeature(page, feature)
  const workbench = panel.locator('.feedback-workbench')
  await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.dataset.playing === 'true')
  const initial = await workbench.evaluate(el => ({ phase: Number(el.dataset.phase), cycle: Number(el.dataset.cycle), rule: el.dataset.rule, playing: el.dataset.playing }))
  assert.deepEqual(initial, { phase: 0, cycle: 0, rule: 'remediate', playing: 'true' }, 'Feedback should start its assessment phase automatically without a click')
  const phase0Emphasis = await readFeedbackRouteEmphasis(workbench)
  assert.equal(phase0Emphasis.phase, 0)
  assert.equal(phase0Emphasis.markerOpacity, 0, 'The route marker should stay dim before its phase arrives')
  const pendingNodeLetterContrast = await contrast(page, workbench.locator('.feedback-adjusted-route > li .node-letter').first(), 'Feedback pending node letter', 3)
  assert.equal(await panel.locator('.feedback-playback').getAttribute('aria-label'), '暂停演示', 'The always-visible playback control should offer pause while the loop is active')
  assert.equal(await panel.locator('.feedback-workbench [aria-live], .feedback-workbench [role="status"], .feedback-workbench [role="alert"]').count(), 0, 'Automatic phases should not be exposed as repeated live announcements')

  const activeFrames = () => page.evaluate(() => window.__feedbackTimerProbe().raf.active)
  const waitPlaying = expected => page.waitForFunction(value => document.querySelector('#feedback-loop .feedback-workbench')?.dataset.playing === String(value), expected)
  await page.waitForFunction(() => window.__feedbackTimerProbe().raf.active.length === 1)
  await page.waitForFunction(() => window.__feedbackTimerProbe().phaseEvents.some(event => event.cycle >= 2), null, { timeout: 34000 })
  const timing = await page.evaluate(() => {
    const probe = window.__feedbackTimerProbe()
    const startIndex = probe.phaseEvents.findIndex(event => event.playing && event.phase === 0 && event.cycle === 0)
    const events = probe.phaseEvents.slice(startIndex).filter((event, index, list) => index === 0 || event.phase !== list[index - 1].phase || event.cycle !== list[index - 1].cycle)
    const transitions = events.slice(1, 7).map((event, index) => ({
      from: `${events[index].cycle}:${events[index].phase}`,
      to: `${event.cycle}:${event.phase}`,
      elapsed: event.at - events[index].at,
    }))
    return { probe, events, transitions, totalElapsed: events.length ? events.at(-1).at - events[0].at : 0 }
  })
  assert.ok(timing.events.length >= 7, 'Automatic feedback should complete at least two full three-phase cycles')
  assert.deepEqual(timing.events.slice(0, 7).map(event => [event.cycle, event.phase]), [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0]], 'Automatic feedback should keep the assessment → reroute → confirmation order across two full cycles')
  assert.ok(timing.totalElapsed >= 23000 && timing.totalElapsed <= 33000, `Two feedback cycles should take about 24 seconds, observed ${timing.totalElapsed.toFixed(0)} ms`)
  const expectedDurations = [3000, 5000, 4000, 3000, 5000, 4000]
  for (let index = 0; index < expectedDurations.length; index++) {
    const transition = timing.transitions[index]
    assert.ok(transition && Math.abs(transition.elapsed - expectedDurations[index]) <= 1000, `Feedback stage ${index + 1} should remain for ${expectedDurations[index]} ms ±1000 ms; observed ${transition?.elapsed?.toFixed(0)} ms`)
  }
  for (const delay of [3000, 5000, 4000]) {
    const observed = timing.probe.fired.filter(timer => timer.kind === 'feedback' && timer.delay === delay)
    assert.ok(observed.length >= 2, `The browser timer probe should observe at least two real ${delay} ms phase timers`)
    for (const timer of observed.slice(0, 2)) assert.ok(Math.abs(timer.firedAt - timer.scheduledAt - delay) <= 1000, `The ${delay} ms stage timer should not be accelerated`)
  }
  evidence.feedbackTimingChecks.push({
    autoStartedWithoutClick: true,
    completeCycles: 2,
    totalElapsedMs: Math.round(timing.totalElapsed),
    transitions: timing.transitions.map(item => ({ ...item, elapsed: Math.round(item.elapsed) })),
    firedTimers: timing.probe.fired.filter(timer => timer.kind === 'feedback'),
  })

  const state = () => workbench.evaluate(el => ({ phase: Number(el.dataset.phase), cycle: Number(el.dataset.cycle), rule: el.dataset.rule, selected: el.querySelector('.feedback-stage[aria-pressed="true"]')?.dataset.feedbackStep }))
  const activeTimers = () => page.evaluate(() => window.__feedbackTimerProbe().active.filter(timer => timer.kind === 'feedback'))
  const pause = panel.getByRole('button', { name: '暂停演示', exact: true })
  await pause.click()
  await waitPlaying(false)
  const pausedState = await state()
  assert.equal(await panel.locator('.feedback-status').innerText(), '演示已暂停', 'Pause should expose its current state')
  assert.equal((await activeTimers()).length, 0, 'Pause should clear the active feedback timeout')
  await page.waitForTimeout(250)
  assert.deepEqual(await state(), pausedState, 'A paused loop should preserve phase and cycle')
  await panel.getByRole('button', { name: '继续演示', exact: true }).click()
  await waitPlaying(true)
  assert.equal((await activeTimers()).length, 1, 'Continue should schedule one feedback timer')

  const focusAndResume = async (locator, label) => {
    await focusFeedbackByKeyboard(page, panel, locator, label)
    await waitPlaying(false)
    assert.match(await panel.locator('.feedback-status').innerText(), /阅读时暂停/, `${label}: entering a feedback control should pause for reading`)
    assert.equal((await activeTimers()).length, 0, `${label}: focus pause should clear the phase timer`)
    assert.equal((await activeFrames()).length, 0, `${label}: keyboard focus hold should cancel the animation frame`)
    await page.locator('#feedback-title').focus()
    await waitPlaying(true)
    assert.equal((await activeTimers()).length, 1, `${label}: leaving feedback controls should resume playback`)
    assert.equal((await activeFrames()).length, 1, `${label}: leaving the keyboard-focused control should restart one animation frame`)
  }
  await focusAndResume(panel.locator('.feedback-rule-options button').nth(1), 'rule focus')
  await focusAndResume(panel.locator('.feedback-stage[data-feedback-step="1"]'), 'step focus')

  const clickEvents = await page.evaluate(() => {
    window.__feedbackClickEvents = []
    document.addEventListener('click', event => {
      const target = event.target instanceof Element ? event.target.closest('.feedback-rule-options button, .feedback-stage') : null
      if (target) window.__feedbackClickEvents.push({ selector: target.matches('.feedback-stage') ? 'stage' : 'rule', detail: event.detail })
    }, true)
    return true
  })
  assert.equal(clickEvents, true)
  const leftCurve = await workbench.evaluate(element => {
    const path = element.querySelector('.feedback-turn-line')
    const totalLength = path.getTotalLength()
    const point = element.querySelector('.feedback-turn-point')
    const expected = { x: Number(point.getAttribute('cx')), y: Number(point.getAttribute('cy')) }
    let nearest = { distance: Infinity, x: null, y: null }
    for (let index = 0; index <= 4096; index++) {
      const sample = path.getPointAtLength(totalLength * index / 4096)
      const distance = Math.hypot(sample.x - expected.x, sample.y - expected.y)
      if (distance < nearest.distance) nearest = { distance, x: sample.x, y: sample.y }
    }
    return { expected, nearest, rule: element.dataset.rule }
  })
  assert.equal(leftCurve.rule, 'remediate')
  assert.deepEqual(leftCurve.expected, { x: 183.75, y: 165.75 }, 'The left turning marker should sit at the exact quadratic midpoint')
  assert.ok(leftCurve.nearest.distance < 0.12, `The left turning marker should lie on its quadratic path: ${JSON.stringify(leftCurve)}`)
  const advanceRule = panel.locator('.feedback-rule-options button').nth(2)
  await focusFeedbackByKeyboard(page, panel, advanceRule, 'pointer rule target')
  await waitPlaying(false)
  await advanceRule.click()
  await waitPlaying(true)
  assert.equal(await workbench.getAttribute('data-rule'), 'advance', 'A real pointer click should select the requested feedback rule')
  assert.equal(await workbench.getAttribute('data-phase'), '0', 'A real pointer rule click should restart its own assessment phase')
  assert.equal((await activeTimers()).length, 1, 'A real pointer rule click should leave automatic playback scheduled')
  assert.equal((await activeFrames()).length, 1, 'A real pointer rule click should keep the route animation frame running')
  const advanceGeometry = await workbench.evaluate(element => {
    const svg = element.querySelector('.feedback-route-canvas svg')
    const path = element.querySelector('.feedback-turn-line')
    const totalLength = path.getTotalLength()
    const turn = element.querySelector('.feedback-turn-point')
    const rect = svg.getBoundingClientRect()
    const toViewBoxX = value => (value - rect.left) / rect.width * 760
    const cards = [...element.querySelectorAll('.feedback-adjusted-route > li')]
    const cardBounds = cards.map(card => {
      const box = card.getBoundingClientRect()
      return { left: toViewBoxX(box.left), right: toViewBoxX(box.right), center: toViewBoxX(box.left + box.width / 2) }
    })
    const start = path.getPointAtLength(0)
    const end = path.getPointAtLength(totalLength)
    const beforeEnd = path.getPointAtLength(Math.max(0, totalLength - 1))
    const expected = { x: Number(turn.getAttribute('cx')), y: Number(turn.getAttribute('cy')) }
    let nearest = Infinity
    for (let index = 0; index <= 4096; index++) {
      const sample = path.getPointAtLength(totalLength * index / 4096)
      nearest = Math.min(nearest, Math.hypot(sample.x - expected.x, sample.y - expected.y))
    }
    return {
      rule: element.dataset.rule,
      nodeLetters: [...element.querySelectorAll('.feedback-adjusted-route .node-letter')].map(node => node.innerText.trim()),
      cardBounds,
      start: { x: start.x, y: start.y },
      end: { x: end.x, y: end.y },
      beforeEnd: { x: beforeEnd.x, y: beforeEnd.y },
      turn: expected,
      curveDistance: nearest,
      moveCount: (path.getAttribute('d').match(/[Mm]/g) || []).length,
    }
  })
  assert.equal(advanceGeometry.rule, 'advance')
  assert.deepEqual(advanceGeometry.nodeLetters, ['A', 'B'], 'The advanced route should preserve A → B node semantics')
  assert.ok(advanceGeometry.cardBounds[0].center < advanceGeometry.cardBounds[1].center, `The advance route should place A on the left and B on the right: ${JSON.stringify(advanceGeometry)}`)
  assert.deepEqual(advanceGeometry.start, { x: 380, y: 130 }, 'The advance route should begin at the current A node')
  assert.ok(Math.abs(advanceGeometry.end.x - 457) < 0.1 && Math.abs(advanceGeometry.end.y - 284) < 0.1, 'The advance route should terminate at the left edge of the B card')
  assert.ok(Math.abs(advanceGeometry.end.x - advanceGeometry.cardBounds[1].left) < 2, `The advance path should point into the second B card: ${JSON.stringify({ end: advanceGeometry.end, secondCard: advanceGeometry.cardBounds[1] })}`)
  assert.ok(advanceGeometry.beforeEnd.x < advanceGeometry.end.x, 'The advance arrow should point from A toward B along the final rightward segment')
  assert.deepEqual(advanceGeometry.turn, { x: 183.75, y: 165.75 }, 'All route branches should share the left quadratic midpoint')
  assert.ok(advanceGeometry.curveDistance < 0.12 && advanceGeometry.moveCount === 1, `The advance curve should remain a single path through its midpoint: ${JSON.stringify(advanceGeometry)}`)

  const advanceStage = panel.locator('.feedback-stage[data-feedback-step="1"]')
  await focusFeedbackByKeyboard(page, panel, advanceStage, 'pointer stage target')
  await waitPlaying(false)
  await advanceStage.click()
  await waitPlaying(true)
  const routeStart = await readFeedbackVisualFrame(workbench)
  assertFeedbackVisualFrame(routeStart, 'phase 1 route start after pointer click')
  assert.ok(routeStart.routeProgress <= 0.05 && routeStart.phaseProgress <= 0.05, `The clicked route should start at its current-node endpoint: ${JSON.stringify(routeStart)}`)
  assert.ok(Math.hypot(routeStart.marker.x - 380, routeStart.marker.y - 130) <= routeStart.pathLength * routeStart.routeProgress + 0.1, 'The starting marker position should match the short distance traveled from A')
  assert.equal(await workbench.getAttribute('data-rule'), 'advance')
  assert.equal(await workbench.getAttribute('data-phase'), '1', 'A real pointer stage click should select the reroute phase')
  assert.equal((await activeTimers()).length, 1, 'A real pointer stage click should preserve automatic phase timing')
  assert.equal((await activeFrames()).length, 1, 'A real pointer stage click should resume RAF-driven route progress')
  await page.waitForFunction(() => {
    const progress = Number(document.querySelector('#feedback-loop .feedback-workbench')?.dataset.routeProgress)
    return progress >= 0.47 && progress <= 0.53
  }, null, { polling: 'raf', timeout: 4000 })
  const routeMiddle = await readFeedbackVisualFrame(workbench)
  assertFeedbackVisualFrame(routeMiddle, 'phase 1 route midpoint after pointer click')
  assert.ok(routeMiddle.routeProgress > routeStart.routeProgress + 0.35, 'The route marker should advance continuously from its start')
  const phase1Emphasis = await readFeedbackRouteEmphasis(workbench)
  assert.equal(phase1Emphasis.phase, 1)
  assert.equal(phase1Emphasis.markerOpacity, 1, 'The route marker should brighten when phase 1 arrives')
  assert.equal(phase1Emphasis.routeLineOpacity, 0.9, 'The route line should brighten only for the arrived phase')
  assert.ok(phase1Emphasis.routeBody.backgroundImage !== phase0Emphasis.routeBody.backgroundImage || phase1Emphasis.routeBody.backgroundColor !== phase0Emphasis.routeBody.backgroundColor, 'The route card should change from its pending dark treatment to its arrived treatment')
  assert.notEqual(phase1Emphasis.routeBody.borderColor, phase0Emphasis.routeBody.borderColor, 'The route card border should change when its phase arrives')
  assert.notEqual(phase1Emphasis.routeCard.backgroundColor, phase0Emphasis.routeCard.backgroundColor, 'The destination cards should remain dark while pending and brighten on arrival')
  assert.notEqual(phase1Emphasis.routeCard.borderColor, phase0Emphasis.routeCard.borderColor, 'The destination card border should brighten on arrival')
  assert.notEqual(phase1Emphasis.nodeLetter.color, phase0Emphasis.nodeLetter.color, 'The node letter should change from pending to arrived text color')
  assert.notEqual(phase1Emphasis.nodeLetter.backgroundColor, phase0Emphasis.nodeLetter.backgroundColor, 'The node letter should receive its highlight only on arrival')
  assert.notEqual(phase1Emphasis.routeState.color, phase0Emphasis.routeState.color, 'The route state label should change color when phase 1 arrives')
  assert.notEqual(phase1Emphasis.turningPointFill, phase0Emphasis.turningPointFill, 'The turning point should brighten only when the route phase arrives')
  const arrivedNodeLetterContrast = await contrast(page, workbench.locator('.feedback-adjusted-route > li .node-letter').first(), 'Feedback arrived node letter', 3)
  assert.ok(arrivedNodeLetterContrast.ratio >= pendingNodeLetterContrast.ratio, `The arrived node highlight must not lower contrast: ${pendingNodeLetterContrast.ratio.toFixed(2)} → ${arrivedNodeLetterContrast.ratio.toFixed(2)}`)

  await panel.locator('.feedback-playback').click()
  await waitPlaying(false)
  const pausedRoute = await readFeedbackVisualFrame(workbench)
  assertFeedbackVisualFrame(pausedRoute, 'mid-route pause')
  assert.equal(pausedRoute.phase, 1, 'Pausing in the reroute phase should preserve the phase')
  assert.ok(Math.abs(pausedRoute.routeProgress - routeMiddle.routeProgress) < 0.035, 'Pausing should preserve the current route position')
  assert.equal((await activeFrames()).length, 0, 'Pause should cancel the feedback animation frame')
  await page.waitForTimeout(180)
  const heldRoute = await readFeedbackVisualFrame(workbench)
  assert.ok(Math.abs(heldRoute.routeProgress - pausedRoute.routeProgress) < 0.00002, 'A paused marker should stay on the same route point')
  assert.ok(Math.abs(heldRoute.phaseProgress - pausedRoute.phaseProgress) < 0.00002, 'A paused phase bar should hold its current fill')
  await panel.getByRole('button', { name: '继续演示', exact: true }).click()
  await waitPlaying(true)
  await page.waitForFunction(() => window.__feedbackTimerProbe().raf.active.length === 1)
  const resumedRoute = await readFeedbackVisualFrame(workbench)
  assertFeedbackVisualFrame(resumedRoute, 'mid-route resume')
  assert.equal(resumedRoute.phase, 1, 'Resume should continue the same reroute phase')
  assert.ok(Math.abs(resumedRoute.routeProgress - pausedRoute.routeProgress) < 0.035, 'Resume should continue from the paused point without a jump or restart')
  await page.waitForFunction(() => Number(document.querySelector('#feedback-loop .feedback-workbench')?.dataset.routeProgress) >= 0.999, null, { polling: 'raf', timeout: 5000 })
  const routeEnd = await readFeedbackVisualFrame(workbench)
  const routeEndAt = await page.evaluate(() => performance.now())
  assertFeedbackVisualFrame(routeEnd, 'phase 1 route end')
  assert.equal(routeEnd.phase, 1, 'The marker should reach the route endpoint before phase 2 begins')
  assert.ok(routeEnd.routeProgress >= 0.999 && routeEnd.phaseProgress >= 0.84 && routeEnd.phaseProgress < 0.92, `The route should finish before the phase bar: ${JSON.stringify(routeEnd)}`)
  await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.dataset.phase === '2', null, { polling: 'raf', timeout: 1600 })
  const phase2At = await page.evaluate(() => performance.now())
  const endpointHoldMs = phase2At - routeEndAt
  assert.ok(endpointHoldMs >= 450 && endpointHoldMs <= 1250, `The route endpoint should hold for about 700 ms before phase 2; observed ${endpointHoldMs.toFixed(0)} ms`)
  const pointerEvents = await page.evaluate(() => window.__feedbackClickEvents)
  assert.deepEqual(pointerEvents.slice(-2), [{ selector: 'rule', detail: 1 }, { selector: 'stage', detail: 1 }], 'Rule and phase automatic-playback checks must use real pointer clicks')
  evidence.feedbackTimingChecks.push({
    realPointerClicks: pointerEvents.slice(-2),
    timeline: {
      start: routeStart, middle: routeMiddle, paused: pausedRoute, held: heldRoute,
      resumed: resumedRoute, end: routeEnd, endpointHoldMs: Math.round(endpointHoldMs),
    },
    curves: { remediate: leftCurve, advance: advanceGeometry },
  })

  await panel.getByRole('button', { name: '暂停演示', exact: true }).click()
  await waitPlaying(false)
  await focusFeedbackByKeyboard(page, panel, panel.locator('.feedback-rule-options button').nth(0), 'explicit pause keyboard focus')
  await waitPlaying(false)
  await page.locator('#feedback-title').focus()
  await page.waitForTimeout(150)
  assert.equal(await workbench.getAttribute('data-playing'), 'false', 'Leaving a focused rule must not override explicit user pause')
  assert.equal((await activeFrames()).length, 0, 'Explicit user pause should retain precedence over focus release')
  await panel.locator('.feedback-rule-options button').nth(2).click()
  await page.waitForTimeout(150)
  assert.equal(await workbench.getAttribute('data-playing'), 'false', 'A pointer rule click must not override explicit user pause')
  assert.equal((await activeTimers()).length, 0, 'Explicit pause should remain free of scheduled phase timers after a pointer rule click')
  await panel.getByRole('button', { name: '继续演示', exact: true }).click()
  await waitPlaying(true)

  // Exercise rapid changes without giving intermediate rule timers a chance to fire.
  for (const index of [0, 1, 2]) await panel.locator('.feedback-rule-options button').nth(index).evaluate(button => button.click())
  assert.equal(await workbench.getAttribute('data-rule'), 'advance', 'Fast rule switching should leave only the final scenario selected')
  assert.equal(await workbench.getAttribute('data-phase'), '0', 'A rule change should restart from assessment')
  assert.equal(await workbench.getAttribute('data-cycle'), '0', 'A new scenario should clear the previous cycle count')
  assert.equal((await activeTimers()).length, 1, 'Rapid rule switching should leave only one current feedback timeout')
  await page.waitForFunction(() => {
    const element = document.querySelector('#feedback-loop .feedback-workbench')
    return element?.dataset.rule === 'advance' && element.dataset.phase === '1'
  }, null, { timeout: 4500 })
  assert.equal(await workbench.getAttribute('data-rule'), 'advance', 'An old rule callback must not overwrite the final selected scenario')
  assert.equal((await activeTimers()).length, 1, 'The next feedback phase should have one fresh timeout')

  const readState = () => workbench.evaluate(el => ({ rule: el.dataset.rule, phase: el.dataset.phase, cycle: el.dataset.cycle, selected: el.querySelector('.feedback-stage[aria-pressed="true"]')?.dataset.feedbackStep }))
  const waitStopped = async label => {
    await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.dataset.playing === 'false', null, { timeout: 2500 })
    const timers = await activeTimers()
    assert.equal(timers.length, 0, `${label}: playback should leave no active phase timeout; remaining timers: ${JSON.stringify(timers)}`)
    assert.equal((await activeFrames()).length, 0, `${label}: playback should leave no active feedback animation frame`)
  }
  const preserveWhileStopped = async label => {
    const before = await readState()
    await page.waitForTimeout(200)
    assert.deepEqual(await readState(), before, `${label}: stopped playback should preserve its selection state`)
    return before
  }

  // Leaving the section and opening the account overlay both set active=false while preserving the local route state.
  const offscreenState = await readState()
  await setScreenImmediately(page, 'learning-path')
  await waitStopped('inactive showcase')
  assert.deepEqual(await preserveWhileStopped('inactive showcase'), offscreenState)
  await setScreenImmediately(page, 'feedback-loop')
  await waitPlaying(true)
  assert.deepEqual(await readState(), offscreenState, 'Returning to the active screen should preserve the current rule and phase')
  assert.equal((await activeTimers()).length, 1, 'Returning to the active screen should resume its timer')

  const beforeAuth = await readState()
  await page.locator('.login-trigger').click()
  await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
  await waitStopped('account overlay')
  assert.deepEqual(await preserveWhileStopped('account overlay'), beforeAuth)
  await page.locator('.modal-close').click()
  await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor({ state: 'hidden' })
  await waitPlaying(true)
  assert.deepEqual(await readState(), beforeAuth, 'Closing the account overlay should resume from the preserved feedback state')

  const beforeHidden = await readState()
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await waitStopped('hidden document')
  assert.deepEqual(await preserveWhileStopped('hidden document'), beforeHidden)
  await page.evaluate(() => {
    delete document.hidden
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await waitPlaying(true)
  assert.deepEqual(await readState(), beforeHidden, 'A visible document should resume the same feedback phase')

  const beforeReduced = await readState()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.classList.contains('is-static'))
  await waitStopped('runtime reduced motion')
  assert.equal(await panel.locator('.feedback-status').innerText(), '减少动态效果 · 三步静态展示')
  assert.equal((await page.evaluate(() => document.querySelector('#feedback-loop .feedback-workbench')?.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length)), 0, 'Runtime reduced motion should stop active SVG/CSS animations')
  assert.equal((await preserveWhileStopped('runtime reduced motion')).rule, beforeReduced.rule)
  assert.equal((await activeTimers()).length, 0, 'Reduced-motion mode should not leave feedback timers scheduled')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.waitForFunction(() => document.querySelector('#feedback-loop .feedback-workbench')?.classList.contains('is-playing'))
  await waitPlaying(true)
  assert.equal(await workbench.getAttribute('data-phase'), '1', 'Restoring motion should resume the documented static phase')
  assert.equal((await activeTimers()).length, 1, 'Restoring motion should start one feedback timer')

  // A route popstate to an unmatched route unmounts LandingView while leaving this document probe alive.
  await panel.locator('.feedback-rule-options button').nth(0).evaluate(button => button.click())
  const beforeUnmountProbe = await page.evaluate(() => window.__feedbackTimerProbe())
  assert.ok(beforeUnmountProbe.visibilityListeners > 0 && beforeUnmountProbe.motionListeners > 0, 'Mounted feedback should own visibility and reduced-motion listeners')
  await page.evaluate(() => {
    history.pushState(history.state, '', '/__feedback_unmount_probe__')
    dispatchEvent(new PopStateEvent('popstate'))
  })
  await page.waitForFunction(() => !document.querySelector('#feedback-loop'), null, { timeout: 3000 })
  await page.waitForFunction(before => {
    const probe = window.__feedbackTimerProbe()
    return probe.active.filter(timer => timer.kind === 'feedback').length === 0 && probe.visibilityListeners < before.visibilityListeners && probe.motionListeners < before.motionListeners
  }, beforeUnmountProbe, { timeout: 3000 })
  const unmountedProbe = await page.evaluate(() => window.__feedbackTimerProbe())
  assert.equal(unmountedProbe.visibilityListeners, beforeUnmountProbe.visibilityListeners - 2, 'Unmount should remove the Feedback and Evidence visibility listeners while preserving unrelated app listeners')
  assert.equal(unmountedProbe.motionListeners, beforeUnmountProbe.motionListeners - 3, 'Unmount should remove the Landing, Feedback and Evidence reduced-motion listeners')
  assert.equal(unmountedProbe.raf.active.length, 0, 'Unmount should cancel the pending feedback animation frame')
  const firedAtUnmount = unmountedProbe.fired.length
  const framesFiredAtUnmount = unmountedProbe.raf.fired.length
  await page.waitForTimeout(3200)
  assert.equal((await page.evaluate(() => window.__feedbackTimerProbe().fired.length)), firedAtUnmount, 'Unmount should prevent the pending feedback callback from firing')
  assert.equal((await page.evaluate(() => window.__feedbackTimerProbe().raf.fired.length)), framesFiredAtUnmount, 'Unmount should prevent further feedback animation frames from firing')
  evidence.feedbackLifecycleChecks.push({
    pauseResume: true, ruleFocusPauseResume: true, stepFocusPauseResume: true, explicitPausePrecedence: true,
    pauseResumeRaf: true, pointerRuleAndStageClicksResume: true, endpointHold: true,
    fastRuleSwitching: true, inactiveSectionPauseResume: true, authOverlayPauseResume: true,
    visibilityChangePauseResume: true, runtimeReducedMotion: true,
    unmount: {
      activeTimers: unmountedProbe.active.filter(timer => timer.kind === 'feedback').length,
      visibilityListenersBefore: beforeUnmountProbe.visibilityListeners,
      visibilityListenersAfter: unmountedProbe.visibilityListeners,
      motionListenersBefore: beforeUnmountProbe.motionListeners,
      motionListenersAfter: unmountedProbe.motionListeners,
    },
  })
}

async function verifyEvidenceAutomaticLoop(page) {
  const feature = features.find(item => item.key === 'evidence')
  const durations = [1800, 2600, 3400, 4200]
  await installShowcaseTimerProbe(page, '#evidence .evidence-archive', 'evidence')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto(routeUrl(feature), { waitUntil: 'domcontentloaded' })
  const panel = await assertFeature(page, feature)
  await page.waitForFunction(expected => document.querySelector('.landing-page')?.dataset.theme === expected, feature.key)
  const archive = panel.locator('.evidence-archive')
  const playback = panel.locator('.trace-playback')
  const evidenceTimers = () => page.evaluate(() => window.__evidenceTimerProbe().active.filter(timer => timer.kind === 'evidence'))
  const activeFrames = () => page.evaluate(() => window.__evidenceTimerProbe().raf.active)
  const waitPlaying = expected => page.waitForFunction(value => document.querySelector('#evidence .evidence-archive')?.dataset.playing === String(value), expected)
  const waitPhase = (expectedPhase, expectedCycle = null) => page.waitForFunction(({ phase, cycle }) => {
    const element = document.querySelector('#evidence .evidence-archive')
    return element?.dataset.phase === String(phase) && (cycle === null || element.dataset.cycle === String(cycle))
  }, { phase: expectedPhase, cycle: expectedCycle }, { polling: 'raf' })
  const pathMetrics = await archive.evaluate(element => {
    const path = element.querySelector('.trace-wiring .trace-signal')
    return { length: path.getTotalLength(), evidenceFraction: 161 / path.getTotalLength() }
  })
  const waitTrace = (kind, timeout = 5000) => page.waitForFunction(({ kind, fraction }) => {
    const element = document.querySelector('#evidence .evidence-archive')
    if (!element) return false
    const progress = Number(element.dataset.traceProgress)
    if (kind === 'evidence-middle') return progress >= fraction * 0.45 && progress <= fraction * 0.55
    if (kind === 'evidence-end') return progress >= fraction - 0.00001
    if (kind === 'source-middle') return progress >= fraction + (1 - fraction) * 0.45 && progress <= fraction + (1 - fraction) * 0.55
    if (kind === 'source-end') return progress >= 1
    if (kind === 'partial-evidence') return progress >= fraction * 0.25 && progress <= fraction * 0.42
    return false
  }, { kind, fraction: pathMetrics.evidenceFraction }, { polling: 'raf', timeout })
  const waitVerdict = kind => page.waitForFunction(({ kind }) => {
    const element = document.querySelector('#evidence .evidence-archive')
    if (!element) return false
    const progress = Number(element.dataset.verdictProgress)
    if (kind === 'middle') return progress >= 0.45 && progress <= 0.55
    if (kind === 'ready') return element.dataset.verdictReady === 'true' && progress >= 1
    return false
  }, { kind }, { polling: 'raf', timeout: kind === 'ready' ? 2500 : 3500 })

  await page.waitForFunction(() => {
    const element = document.querySelector('#evidence .evidence-archive')
    return element?.dataset.phase === '0' && element.dataset.cycle === '0' && element.dataset.playing === 'true'
  })
  assert.equal(await archive.getAttribute('data-verdict'), 'supported', 'The natural loop should begin with the supported Claim rule')
  assert.equal(await archive.getAttribute('data-verdict-ready'), 'false', 'The independent verdict should begin unready')
  const claimStart = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(claimStart, 'cycle 0 Claim start')
  assert.equal(claimStart.traceProgress, 0)
  assert.equal(claimStart.verdictReady, false)
  assert.equal(claimStart.verdictProgress, 0)
  assert.equal(claimStart.verdictCardReady, false)
  assert.equal(claimStart.sourceState, 'pending')
  await page.waitForTimeout(240)
  const claimHold = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(claimHold.traceProgress - claimStart.traceProgress) < 0.00002, 'Phase 0 should hold the marker at Claim')
  assert.ok(Math.hypot(claimHold.marker.x - claimStart.marker.x, claimHold.marker.y - claimStart.marker.y) < 0.03, 'Phase 0 should not move the main trace marker')

  await waitPhase(1, 0)
  const phase1Start = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(phase1Start, 'cycle 0 Evidence route start')
  await waitTrace('evidence-middle')
  const evidenceMiddle = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(evidenceMiddle, 'cycle 0 Evidence midpoint')
  assert.equal(evidenceMiddle.phase, 1)
  assert.equal(evidenceMiddle.evidenceState, 'active', 'Evidence should brighten when phase 1 arrives')
  assert.notEqual(evidenceMiddle.evidenceTitleColor, claimStart.evidenceTitleColor)
  assert.equal(evidenceMiddle.sourceState, 'pending')
  assert.equal(evidenceMiddle.sourceActive, false)
  assert.equal(evidenceMiddle.verdictReady, false, 'The independent verdict must wait through the Evidence phase')

  await waitTrace('evidence-end')
  const evidenceEnd = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(evidenceEnd, 'cycle 0 Evidence endpoint')
  assert.equal(evidenceEnd.phase, 1)
  assert.ok(Math.hypot(evidenceEnd.marker.x - 33, evidenceEnd.marker.y - 242) <= 0.03, 'The first route should end at Evidence (33,242)')
  assert.ok(evidenceEnd.phaseProgress >= 0.82 && evidenceEnd.phaseProgress < 0.92, 'The main marker should arrive about 400 ms before phase 1 ends')
  assert.equal(evidenceEnd.sourceState, 'pending')
  assert.equal(evidenceEnd.verdictReady, false)
  const evidenceEndAt = await page.evaluate(() => performance.now())
  await waitPhase(2, 0)
  // Measure elapsed in the browser's monotonic clock after observing the phase transition.
  const evidenceHoldObserved = await page.evaluate(start => performance.now() - start, evidenceEndAt)
  assert.ok(evidenceHoldObserved >= 220 && evidenceHoldObserved <= 850, `Evidence should hold about 400 ms before Source; observed ${evidenceHoldObserved.toFixed(0)} ms`)

  const phase2Start = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(phase2Start, 'cycle 0 Source route start')
  assert.ok(Math.abs(phase2Start.traceProgress - evidenceEnd.traceProgress) < 0.005, 'Phase 2 should continue from Evidence without resetting')
  assert.equal(phase2Start.sourceState, 'located')
  assert.equal(phase2Start.sourceActive, true)
  await waitTrace('source-middle')
  const sourceMiddle = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(sourceMiddle, 'cycle 0 Source midpoint')
  assert.equal(sourceMiddle.phase, 2)
  assert.equal(sourceMiddle.sourceState, 'located')
  assert.equal(sourceMiddle.sourceActive, true)
  assert.equal(sourceMiddle.sourceReached, true)
  assert.notEqual(sourceMiddle.sourceTitleColor, claimStart.sourceTitleColor)
  assert.notEqual(sourceMiddle.sourceBorderColor, claimStart.sourceBorderColor)
  assert.equal(sourceMiddle.verdictReady, false, 'The fourth decision must remain unready while the main source route is active')

  await waitTrace('source-end')
  const sourceEnd = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(sourceEnd, 'cycle 0 Source endpoint')
  assert.equal(sourceEnd.phase, 2)
  assert.ok(Math.hypot(sourceEnd.marker.x - 387, sourceEnd.marker.y - 122) <= 0.03, `The main route should reach Source (387,122): ${JSON.stringify({ progress: sourceEnd.traceProgress, marker: sourceEnd.marker, expected: sourceEnd.expected })}`)
  assert.ok(sourceEnd.phaseProgress >= 0.80 && sourceEnd.phaseProgress < 0.90, 'The main marker should reach Source before phase 2 ends')
  assert.equal(sourceEnd.verdictReady, false)
  const sourceEndAt = await page.evaluate(() => performance.now())
  await waitPhase(3, 0)
  const sourceEndpointHoldMs = await page.evaluate(start => performance.now() - start, sourceEndAt)
  assert.ok(sourceEndpointHoldMs >= 400 && sourceEndpointHoldMs <= 1050, `Source should hold about 600 ms before the separate verdict phase; observed ${sourceEndpointHoldMs.toFixed(0)} ms`)

  const verdictStart = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(verdictStart, 'cycle 0 final-route start')
  assert.equal(verdictStart.phase, 3)
  assert.ok(verdictStart.verdictProgress >= 0 && verdictStart.verdictProgress <= 0.05, `The final route start sample should remain at its beginning; observed progress ${verdictStart.verdictProgress}`)
  assert.equal(verdictStart.verdictReady, false, 'The result must remain hidden until its own terminal light arrives')
  assert.equal(verdictStart.verdictCardReady, false)
  assert.equal(verdictStart.verdictLabel, '等待独立判定')
  assert.equal(verdictStart.sourceState, 'located')
  assert.ok(verdictStart.verdictStart && verdictStart.verdictEnd && verdictStart.verdictPathLength > 90, 'Source-to-verdict wiring should be a longer independent route')
  const supportedLayout = await assertEvidenceComposition(panel, 'evidence/supported-terminal-path')
  await waitVerdict('middle')
  const verdictMiddle = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(verdictMiddle, 'cycle 0 final-route midpoint')
  assert.equal(verdictMiddle.phase, 3)
  assert.ok(verdictMiddle.verdictProgress >= 0.45 && verdictMiddle.verdictProgress <= 0.55)
  assert.equal(verdictMiddle.verdictReady, false)
  assert.equal(verdictMiddle.verdictCardReady, false)
  assert.equal(verdictMiddle.verdictLabel, '等待独立判定')
  assert.ok(verdictMiddle.finalLightOpacity > 0, 'The terminal light should visibly move along the independent verdict route')
  const verdictPendingStyle = { border: verdictMiddle.verdictBorderColor, background: verdictMiddle.verdictBackgroundColor, label: verdictMiddle.verdictLabelColor }
  await waitVerdict('ready')
  const readyAt = await page.evaluate(() => performance.now())
  const verdictEndpoint = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(verdictEndpoint, 'cycle 0 final-route endpoint')
  assert.equal(verdictEndpoint.verdictProgress, 1)
  assert.equal(verdictEndpoint.verdictReady, true, 'data-verdict-ready must become true only at the terminal point')
  assert.ok(verdictEndpoint.verdictMarker && verdictEndpoint.verdictEnd)
  assert.ok(Math.hypot(verdictEndpoint.verdictMarker.x - verdictEndpoint.verdictEnd.x, verdictEndpoint.verdictMarker.y - verdictEndpoint.verdictEnd.y) <= 0.03, 'The terminal light should arrive at the independent decision card')
  assert.equal(verdictEndpoint.verdictCardReady, true)
  assert.equal(verdictEndpoint.verdictLabel, '有证据支持')
  await page.waitForTimeout(850)
  const verdictLit = await readEvidenceVisualFrame(archive)
  assert.notEqual(verdictLit.verdictBorderColor, verdictPendingStyle.border, 'The fourth-step card border should brighten only after terminal arrival')
  assert.notEqual(verdictLit.verdictBackgroundColor, verdictPendingStyle.background, 'The fourth-step card should brighten only after terminal arrival')
  assert.notEqual(verdictLit.verdictLabelColor, verdictPendingStyle.label, 'The result label should receive its verdict color only after terminal arrival')

  await waitPhase(0, 1)
  const firstReadyHoldMs = await page.evaluate(start => performance.now() - start, readyAt)
  assert.ok(firstReadyHoldMs >= 2200 && firstReadyHoldMs <= 3200, `A ready verdict should remain visible about 2700 ms before the next cycle; observed ${firstReadyHoldMs.toFixed(0)} ms`)

  await waitPhase(1, 1)
  await waitPhase(2, 1)
  await waitPhase(3, 1)
  await waitVerdict('ready')
  const secondCycleReady = await readEvidenceVisualFrame(archive)
  assert.equal(secondCycleReady.cycle, 1)
  assert.equal(secondCycleReady.verdictReady, true, 'The second automatic cycle should also reach its terminal light')
  const secondReadyAt = await page.evaluate(() => performance.now())
  await waitPhase(0, 2)
  const secondReadyHoldMs = await page.evaluate(start => performance.now() - start, secondReadyAt)
  assert.ok(secondReadyHoldMs >= 2200 && secondReadyHoldMs <= 3200, `The second cycle result should also hold before looping; observed ${secondReadyHoldMs.toFixed(0)} ms`)

  const timing = await page.evaluate(() => {
    const probe = window.__evidenceTimerProbe()
    const events = probe.phaseEvents.filter(event => event.rule === 'supported')
    const startIndex = events.findIndex(event => event.cycle === 0 && event.phase === 0 && event.playing)
    const run = events.slice(startIndex)
    const phaseStarts = []
    const keys = new Set()
    for (const event of run) {
      const key = `${event.cycle}:${event.phase}`
      if (event.playing && !keys.has(key)) {
        keys.add(key)
        phaseStarts.push(event)
      }
    }
    const readyEvents = run.filter(event => event.verdictReady)
    const transitions = phaseStarts.slice(1, 9).map((event, index) => ({ from: `${phaseStarts[index].cycle}:${phaseStarts[index].phase}`, to: `${event.cycle}:${event.phase}`, elapsed: event.at - phaseStarts[index].at }))
    return {
      phaseStarts,
      readyEvents,
      transitions,
      totalElapsed: phaseStarts[8].at - phaseStarts[0].at,
      fired: probe.fired.filter(timer => timer.kind === 'evidence'),
      delay1800Ownership: probe.scheduled.filter(timer => timer.delay === 1800).map(timer => ({ kind: timer.kind, agentPanelActiveAtSchedule: timer.agentPanelActiveAtSchedule, agentSceneRunningAtSchedule: timer.agentSceneRunningAtSchedule, handlerCaller: timer.handlerCaller })),
    }
  })
  assert.deepEqual(timing.phaseStarts.slice(0, 9).map(event => [event.cycle, event.phase]), [[0, 0], [0, 1], [0, 2], [0, 3], [1, 0], [1, 1], [1, 2], [1, 3], [2, 0]], `The evidence loop should complete two ordered cycles: ${JSON.stringify(timing.phaseStarts)}`)
  assert.deepEqual(timing.transitions.map(item => [item.from, item.to]), [['0:0', '0:1'], ['0:1', '0:2'], ['0:2', '0:3'], ['0:3', '1:0'], ['1:0', '1:1'], ['1:1', '1:2'], ['1:2', '1:3'], ['1:3', '2:0']])
  const expectedTransitions = [...durations, ...durations]
  for (let index = 0; index < expectedTransitions.length; index++) {
    assert.ok(Math.abs(timing.transitions[index].elapsed - expectedTransitions[index]) <= 700, `Evidence cycle transition ${index + 1} should last ${expectedTransitions[index]} ms ±700 ms; observed ${timing.transitions[index].elapsed.toFixed(0)} ms`)
  }
  assert.ok(timing.totalElapsed >= 22500 && timing.totalElapsed <= 25500, `Two automatic evidence cycles should take about 24 seconds; observed ${timing.totalElapsed.toFixed(0)} ms`)
  assert.deepEqual(timing.readyEvents.slice(0, 2).map(event => event.cycle), [0, 1], 'Both cycles should emit a real terminal-ready state')
  assert.deepEqual(timing.fired.slice(0, 8).map(timer => timer.delay), expectedTransitions, 'Each of the two cycles should use all four declared real timers')
  for (const timer of timing.fired.slice(0, 8)) assert.ok(Math.abs(timer.firedAt - timer.scheduledAt - timer.delay) <= 700, `The ${timer.delay} ms phase timer should not be accelerated`)
  assert.ok(timing.delay1800Ownership.length >= 2, 'Evidence should schedule its 1800 ms phase timer in both natural cycles')
  assert.ok(timing.delay1800Ownership.every(timer => timer.kind === 'evidence' && !timer.agentPanelActiveAtSchedule), 'Evidence 1800 ms timers must remain attributed to Evidence because the Agent panel is inactive')
  evidence.evidenceTimingChecks.push({
    viewport: { width: 1331, height: 871, scale: 1.5 },
    autoStartedWithoutClick: true,
    cycles: 2,
    durationsMs: durations,
    transitions: timing.transitions.map(item => ({ ...item, elapsed: Math.round(item.elapsed) })),
    totalElapsedMs: Math.round(timing.totalElapsed),
    delay1800Ownership: timing.delay1800Ownership,
    readyResultHoldsMs: [Math.round(firstReadyHoldMs), Math.round(secondReadyHoldMs)],
    routeFrames: { claimStart, claimHold, phase1Start, evidenceMiddle, evidenceEnd, phase2Start, sourceMiddle, sourceEnd, verdictStart, verdictMiddle, verdictEndpoint, verdictLit },
    terminalGeometry: { start: supportedLayout.verdictPathStart, end: supportedLayout.verdictPathEnd, cardTarget: supportedLayout.verdictTarget, endpointErrorPx: supportedLayout.verdictEndpointError, connectorGaps: supportedLayout.connectorGeometry.map(item => item.gap) },
  })

  const ruleChoice = panel.getByRole('button', { name: '查看判定规则：有证据支持', exact: true })
  const missingChoice = panel.getByRole('button', { name: '查看判定规则：当前无依据', exact: true })
  await missingChoice.click()
  await page.waitForFunction(() => {
    const element = document.querySelector('#evidence .evidence-archive')
    return element?.dataset.verdict === 'not_in_evidence' && element.dataset.phase === '0' && element.dataset.cycle === '0' && element.dataset.playing === 'true'
  })
  await waitPhase(1, 0)
  await waitTrace('evidence-end')
  const missingEvidenceEnd = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(missingEvidenceEnd, 'missing Claim Evidence endpoint')
  assert.equal(missingEvidenceEnd.sourceState, 'unbound')
  assert.equal(missingEvidenceEnd.sourceReached, false)
  assert.ok(Math.hypot(missingEvidenceEnd.marker.x - 33, missingEvidenceEnd.marker.y - 242) <= 0.03, 'A missing Claim should stop its main light at Evidence')
  await waitPhase(2, 0)
  await page.waitForFunction(() => {
    const element = document.querySelector('#evidence .evidence-archive')
    const progress = Number(element?.dataset.phaseProgress)
    return element?.dataset.phase === '2' && progress >= 0.45 && progress <= 0.55
  }, null, { polling: 'raf' })
  const missingSourceHold = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(missingSourceHold, 'missing Claim Source-phase hold')
  assert.ok(Math.abs(missingSourceHold.traceProgress - pathMetrics.evidenceFraction) < 0.00002, 'The missing Claim main light must not move toward Source')
  assert.equal(missingSourceHold.sourceState, 'unbound')
  assert.equal(missingSourceHold.sourceActive, false)
  assert.equal(missingSourceHold.sourceReached, false)
  assert.equal(missingSourceHold.verdictReady, false)
  const missingVerdictStart = await readEvidenceVisualFrame(archive, 3)
  assert.equal(missingVerdictStart.cycle, 0, 'Missing-Claim start must belong to the same natural cycle')
  assertEvidenceVisualFrame(missingVerdictStart, 'missing Claim direct-to-verdict start')
  assert.ok(Math.abs(missingVerdictStart.verdictProgress) <= 0.005, `The missing-Claim final route should begin at its start; observed progress ${missingVerdictStart.verdictProgress}`)
  const missingLayout = await assertEvidenceComposition(panel, 'evidence/not-in-evidence')
  assert.ok(Math.hypot(missingLayout.verdictPathStart.x - missingLayout.evidenceEnd.x, missingLayout.verdictPathStart.y - missingLayout.evidenceEnd.y) <= 2, 'The unbound verdict route should start at Evidence instead of Source')
  await waitVerdict('middle')
  const missingVerdictMiddle = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(missingVerdictMiddle, 'missing Claim verdict-route midpoint')
  assert.equal(missingVerdictMiddle.sourceState, 'unbound')
  assert.equal(missingVerdictMiddle.sourceReached, false)
  assert.equal(missingVerdictMiddle.verdictReady, false)
  assert.equal(missingVerdictMiddle.verdictLabel, '等待独立判定')
  const missingResult = await waitForEvidenceVerdictReady(page, 'natural missing-Claim verdict arrival')
  assert.equal(missingResult.rule, 'not_in_evidence')
  assert.equal(missingResult.sourceState, 'unbound')
  assert.equal(missingResult.verdict, '当前无依据')
  const missingVerdictEnd = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(missingVerdictEnd, 'missing Claim verdict-route endpoint')
  assert.equal(missingVerdictEnd.traceProgress.toFixed(5), pathMetrics.evidenceFraction.toFixed(5), 'The missing Claim must never route its main light to Source')
  assert.equal(missingVerdictEnd.sourceReached, false)
  assert.equal(missingVerdictEnd.verdictReady, true)
  assert.equal(missingVerdictEnd.verdictLabel, '当前无依据')
  await page.waitForTimeout(850)
  assert.equal((await readEvidenceVisualFrame(archive)).verdictCardReady, true, 'The missing-Claim fourth-step card should highlight after its terminal light arrives')
  evidence.evidenceTimingChecks.push({ missingPolicy: { endpoint: { x: missingEvidenceEnd.marker.x, y: missingEvidenceEnd.marker.y }, sourceState: missingSourceHold.sourceState, directVerdictStart: missingLayout.verdictPathStart, evidenceEnd: missingLayout.evidenceEnd, result: missingResult } })

  // Continue from the explicit capture pause, then exercise the same-time route with pause/resume and focus holds.
  await ruleChoice.click()
  assert.equal(await archive.getAttribute('data-cycle'), '0')
  assert.equal(await archive.getAttribute('data-phase'), '0')
  assert.equal(await archive.getAttribute('data-playing'), 'false', 'Changing the rule must preserve an explicit capture pause')
  await playback.click()
  await waitPlaying(true)
  await waitPhase(1, 0)
  await waitTrace('partial-evidence')
  const playbackStart = await readEvidenceVisualFrame(archive)
  await playback.click()
  await waitPlaying(false)
  const paused = await readEvidenceVisualFrame(archive)
  assert.equal(paused.phase, 1)
  assert.ok(Math.abs(paused.traceProgress - playbackStart.traceProgress) < 0.035, 'Pause should hold the in-flight trace point instead of restarting')
  assert.equal((await evidenceTimers()).length, 0, 'Pause should clear the Evidence phase timer')
  assert.equal((await activeFrames()).length, 0, 'Pause should cancel the RAF-driven marker update')
  await page.waitForTimeout(220)
  const pausedHold = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(pausedHold.traceProgress - paused.traceProgress) < 0.00002, 'Pause should hold the trace point exactly')
  assert.ok(Math.abs(pausedHold.phaseProgress - paused.phaseProgress) < 0.00002, 'Pause should hold phase progress exactly')
  await playback.click()
  await waitPlaying(true)
  const resumed = await readEvidenceVisualFrame(archive)
  assert.equal(resumed.phase, paused.phase)
  assert.ok(Math.abs(resumed.traceProgress - paused.traceProgress) < 0.035, 'Resume should continue at the same point')

  await focusEvidenceRuleByKeyboard(page, ruleChoice, 'Evidence keyboard focus hold')
  await waitPlaying(false)
  const focusPaused = await readEvidenceVisualFrame(archive)
  assert.equal((await evidenceTimers()).length, 0, 'Keyboard-visible focus should clear the Evidence timer')
  assert.equal((await activeFrames()).length, 0, 'Keyboard-visible focus should cancel the Evidence RAF loop')
  await page.waitForTimeout(180)
  const focusHeld = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(focusHeld.traceProgress - focusPaused.traceProgress) < 0.00002, 'Keyboard focus should keep the trace point still')
  await page.locator('#evidence-title').focus()
  await waitPlaying(true)
  const focusResumed = await readEvidenceVisualFrame(archive)
  assert.equal(focusResumed.phase, focusPaused.phase)
  assert.ok(Math.abs(focusResumed.traceProgress - focusPaused.traceProgress) < 0.035, 'Leaving the keyboard-focused rule should resume at the same point')

  await playback.click()
  await waitPlaying(false)
  await focusEvidenceRuleByKeyboard(page, ruleChoice, 'explicit pause focus precedence')
  await waitPlaying(false)
  await page.locator('#evidence-title').focus()
  await page.waitForTimeout(160)
  assert.equal(await archive.getAttribute('data-playing'), 'false', 'Leaving a keyboard-focused rule must not override explicit pause')
  await ruleChoice.click()
  assert.equal(await archive.getAttribute('data-cycle'), '0', 'A pointer rule selection should reset to cycle 0')
  assert.equal(await archive.getAttribute('data-phase'), '0')
  assert.equal(await archive.getAttribute('data-playing'), 'false', 'A pointer rule selection must preserve explicit pause')
  assert.equal((await evidenceTimers()).length, 0)
  assert.equal((await activeFrames()).length, 0)
  await panel.getByRole('button', { name: '继续溯源演示', exact: true }).click()
  await waitPlaying(true)

  await waitPhase(1, 0)
  await waitTrace('partial-evidence')
  const offscreenBefore = await readEvidenceVisualFrame(archive)
  await setScreenImmediately(page, 'learning-path')
  await waitPlaying(false)
  assert.equal((await evidenceTimers()).length, 0, 'Leaving Evidence should clear its timer')
  assert.equal((await activeFrames()).length, 0, 'Leaving Evidence should cancel its RAF loop')
  const offscreenStopped = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(offscreenStopped.traceProgress - offscreenBefore.traceProgress) < 0.035)
  await page.waitForTimeout(180)
  const offscreenHeld = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(offscreenHeld.traceProgress - offscreenStopped.traceProgress) < 0.00002, 'Off-screen Evidence should hold its progress')
  await setScreenImmediately(page, 'evidence')
  await waitPlaying(true)
  const offscreenResumed = await readEvidenceVisualFrame(archive)
  assert.equal(offscreenResumed.phase, offscreenStopped.phase)
  assert.ok(Math.abs(offscreenResumed.traceProgress - offscreenStopped.traceProgress) < 0.035, 'Returning to the active section should resume without a jump')

  const hiddenBefore = await readEvidenceVisualFrame(archive)
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await waitPlaying(false)
  assert.equal((await evidenceTimers()).length, 0, 'A hidden page should clear the Evidence timer')
  assert.equal((await activeFrames()).length, 0, 'A hidden page should stop the Evidence RAF loop')
  const hiddenStopped = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(hiddenStopped.traceProgress - hiddenBefore.traceProgress) < 0.035)
  await page.waitForTimeout(180)
  const hiddenHeld = await readEvidenceVisualFrame(archive)
  assert.ok(Math.abs(hiddenHeld.traceProgress - hiddenStopped.traceProgress) < 0.00002, 'A hidden page should preserve Evidence progress')
  await page.evaluate(() => {
    delete document.hidden
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await waitPlaying(true)
  const visibleResume = await readEvidenceVisualFrame(archive)
  assert.equal(visibleResume.phase, hiddenStopped.phase)
  assert.ok(Math.abs(visibleResume.traceProgress - hiddenStopped.traceProgress) < 0.035, 'Visibility restoration should resume without jumping')

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.waitForFunction(() => {
    const element = document.querySelector('#evidence .evidence-archive')
    return element?.dataset.phase === '3' && element.dataset.verdictReady === 'true' && element.dataset.playing === 'false'
  })
  const reduced = await readEvidenceVisualFrame(archive)
  assertEvidenceVisualFrame(reduced, 'runtime reduced-motion Evidence state')
  assert.equal(reduced.traceProgress, 1)
  assert.equal(reduced.verdictProgress, 1)
  assert.equal(reduced.verdictReady, true)
  assert.equal((await evidenceTimers()).length, 0, 'Reduced motion should leave no Evidence timer')
  assert.equal((await activeFrames()).length, 0, 'Reduced motion should stop the Evidence RAF loop')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.waitForFunction(() => document.querySelector('#evidence .evidence-archive')?.dataset.phase === '0' && document.querySelector('#evidence .evidence-archive')?.dataset.playing === 'true')
  const ruleChoiceAfterMotion = panel.getByRole('button', { name: '查看判定规则：有证据支持', exact: true })
  await ruleChoiceAfterMotion.click()
  await waitPlaying(true)
  assert.equal((await evidenceTimers()).length, 1, 'Normal motion should schedule an Evidence phase timer')
  assert.equal((await activeFrames()).length, 1, 'Normal motion should start one Evidence RAF callback')

  const beforeUnmount = await page.evaluate(() => window.__evidenceTimerProbe())
  assert.ok(beforeUnmount.visibilityListeners > 0 && beforeUnmount.motionListeners > 0, 'Mounted Evidence should own visibility and reduced-motion listeners')
  assert.ok(beforeUnmount.resizeObservers > 0, 'Mounted Evidence should own a ResizeObserver')
  assert.equal(beforeUnmount.active.filter(timer => timer.kind === 'evidence').length, 1)
  await page.evaluate(() => {
    history.pushState(history.state, '', '/__evidence_unmount_probe__')
    dispatchEvent(new PopStateEvent('popstate'))
  })
  await page.waitForFunction(() => !document.querySelector('#evidence .evidence-archive'), null, { timeout: 3000 })
  await page.waitForFunction(before => {
    const probe = window.__evidenceTimerProbe()
    return probe.active.filter(timer => timer.kind === 'evidence').length === 0 && probe.visibilityListeners < before.visibilityListeners && probe.motionListeners < before.motionListeners && probe.resizeObservers < before.resizeObservers
  }, beforeUnmount, { timeout: 3000 })
  const afterUnmount = await page.evaluate(() => window.__evidenceTimerProbe())
  assert.equal(afterUnmount.visibilityListeners, beforeUnmount.visibilityListeners - 2, 'Unmount should clear the Evidence and Feedback visibility listeners while preserving unrelated app listeners')
  assert.equal(afterUnmount.motionListeners, beforeUnmount.motionListeners - 3, 'Unmount should clear the Landing, Evidence and Feedback reduced-motion listeners')
  assert.equal(afterUnmount.resizeObservers, beforeUnmount.resizeObservers - 2, 'Full LandingView unmount should disconnect its screen observer and the Evidence observer')
  assert.equal(afterUnmount.raf.active.length, 0)
  const evidenceTimersAtUnmount = afterUnmount.fired.filter(timer => timer.kind === 'evidence').length
  const framesAtUnmount = afterUnmount.raf.fired.length
  await page.waitForTimeout(1900)
  const postUnmount = await page.evaluate(() => window.__evidenceTimerProbe())
  assert.equal(postUnmount.fired.filter(timer => timer.kind === 'evidence').length, evidenceTimersAtUnmount, 'Unmount should prevent the pending phase timeout from firing')
  assert.equal(postUnmount.raf.fired.length, framesAtUnmount, 'Unmount should prevent additional Evidence frames')
  evidence.evidenceLifecycleChecks.push({
    pauseResume: { phase: paused.phase, progress: paused.traceProgress, resumedProgress: resumed.traceProgress },
    keyboardFocusPauseResume: true,
    explicitPausePrecedence: true,
    offscreenPauseResume: true,
    hiddenPagePauseResume: true,
    runtimeReducedMotion: true,
    unmount: {
      listeners: { visibility: [beforeUnmount.visibilityListeners, afterUnmount.visibilityListeners], motion: [beforeUnmount.motionListeners, afterUnmount.motionListeners] },
      resizeObservers: [beforeUnmount.resizeObservers, afterUnmount.resizeObservers],
      activeTimers: afterUnmount.active.filter(timer => timer.kind === 'evidence').length,
      activeFrames: afterUnmount.raf.active.length,
      waitedAfterUnmountMs: 1900,
    },
  })
}
try {
  // This acceptance gate requires a locally installed Microsoft Edge; missing Edge is a failure.
  browser = await chromium.launch(browserOptions('FEATURE_SHOWCASE_BROWSER_CHANNEL'))

  for (const feature of features) {
    const direct = await newPage()
    await direct.goto(base + feature.legacyPath, { waitUntil: 'networkidle' })
    await direct.waitForURL(routeUrl(feature))
    await assertFeature(direct, feature)
    await direct.reload({ waitUntil: 'networkidle' })
    await assertFeature(direct, feature)
    evidence.routes.push({ legacyPath: feature.legacyPath, redirectedTo: routeUrl(feature), direct: 'PASS', reload: 'PASS', feature: feature.key })
    await direct.close()
  }

  for (const feature of features) {
    for (const viewport of viewports) {
      const page = await newPage({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: viewport.scale,
      })
      await openFeature(page, feature)
      await geometry(page, feature, viewport)
      if (feature.key === 'agents' && viewport.name === 'desktop') {
        const orbit = assertAgentOrbitGeometry(await inspectAgentOrbit(page.locator('#multi-agent .agent-constellation')), 'Agent 1257×860 desktop', { noOverlap: true })
        evidence.agentGeometryChecks.push({ viewport: { width: viewport.width, height: viewport.height, scale: viewport.scale }, ...orbit })
      }
      if (feature.key === 'agents' && viewport.name === 'mobile') {
        const orbit = assertAgentOrbitGeometry(await inspectAgentOrbit(page.locator('#multi-agent .agent-constellation')), 'Agent 390×844 mobile')
        evidence.agentGeometryChecks.push({ viewport: { width: viewport.width, height: viewport.height, scale: viewport.scale }, ...orbit, mobileContainment: 'PASS' })
      }
      if (viewport.name === 'desktop' || viewport.name === 'mobile') await screenshot(page, feature, viewport)
      for (const [index, control] of controlsFor(page, feature).entries()) {
        await reachable(control, feature.id + '/' + viewport.name + '/control-' + (index + 1))
      }
      if (feature.key === 'evidence' && viewport.name === 'mobile') {
        for (const label of ['有证据支持', '当前无依据', '与来源矛盾']) {
          await page.locator('#evidence').getByRole('button', { name: `查看判定规则：${label}`, exact: true }).click()
          await assertEvidenceMobileFlow(page.locator('#evidence.showcase-panel'))
        }
      }
      if (feature.key === 'feedback') {
        for (const label of ['补基础', '纠错巩固', '继续进阶']) {
          await page.locator('#feedback-loop').getByRole('button', { name: `查看反馈规则：${label}`, exact: true }).click()
          await assertFeedbackRouteLayout(page.locator('#feedback-loop.showcase-panel'), `${viewport.name}/${label}`)
        }
      }
      await page.close()
    }
  }

  const wideAgentGeometryPage = await newPage({ viewport: { width: 1331, height: 871 }, deviceScaleFactor: 1.5 })
  await openFeature(wideAgentGeometryPage, features.find(feature => feature.key === 'agents'))
  const wideAgentOrbit = assertAgentOrbitGeometry(await inspectAgentOrbit(wideAgentGeometryPage.locator('#multi-agent .agent-constellation')), 'Agent 1331×871 desktop', { noOverlap: true })
  evidence.agentGeometryChecks.push({ viewport: { width: 1331, height: 871, scale: 1.5 }, ...wideAgentOrbit })
  await wideAgentGeometryPage.close()

  const compactEvidencePage = await newPage({
    viewport: { width: 1024, height: 768 },
    deviceScaleFactor: 1,
  })
  const evidenceFeature = features.find(feature => feature.key === 'evidence')
  const compactEvidencePanel = await openFeature(compactEvidencePage, evidenceFeature)
  await compactEvidencePanel.getByRole('button', { name: '查看判定规则：与来源矛盾', exact: true }).click()
  await waitForVisualStability(compactEvidencePage)
  await geometry(compactEvidencePage, evidenceFeature, { name: 'compact', width: 1024, height: 768 })
  const compactSourceLayout = await compactEvidencePage.evaluate(() => {
    const panel = document.querySelector('#evidence.showcase-panel')
    const main = document.querySelector('.landing-main')
    const archive = panel?.querySelector('.evidence-archive')
    const source = panel?.querySelector('.trace-source')
    const title = source?.querySelector('h3')
    const box = element => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }
    }
    return { main: box(main), archive: box(archive), source: box(source), title: box(title), titleText: title?.innerText || '' }
  })
  assert.equal(compactSourceLayout.titleText, '定位原始来源', 'The compact Claim trace should show the source-locator stage')
  assert.ok(compactSourceLayout.source && compactSourceLayout.archive && compactSourceLayout.main, 'The source-locator stage and screen should be measurable')
  assert.ok(compactSourceLayout.source.top >= compactSourceLayout.main.top - 1 && compactSourceLayout.source.bottom <= compactSourceLayout.main.bottom + 1, 'The source-locator stage should remain inside the compact evidence screen')
  assert.ok(compactSourceLayout.source.top >= compactSourceLayout.archive.top && compactSourceLayout.source.bottom <= compactSourceLayout.archive.bottom, 'The source-locator stage should remain inside the evidence scene')
  await assertEvidenceComposition(compactEvidencePanel, 'compact/contradicted')
  assert.ok(compactSourceLayout.title.top >= compactSourceLayout.source.top && compactSourceLayout.title.bottom <= compactSourceLayout.source.bottom, 'The long third source title should remain inside its source card')
  assert.ok(compactSourceLayout.title.scrollHeight <= compactSourceLayout.title.clientHeight + 1, 'The long third source title should not be clipped')
  evidence.traceLayoutChecks.push({ viewport: { width: 1024, height: 768 }, ...compactSourceLayout })
  await compactEvidencePage.close()

  for (const feature of features) {
    const page = await newPage()
    await openFeature(page, feature)
    await assertDemoMark(page, feature)
    await verifyInteractions(page, feature)
    await verifyTheme(page, feature)
    const panel = page.locator('#' + feature.id + '.showcase-panel')
    await contrast(page, panel.locator('.feature-intro > p').first(), feature.id + ' key paragraph')
    await contrast(page, panel.locator('button').first(), feature.id + ' key control')
    await verifyFocus(page, feature)
    await verifyMotionPreference(page, feature)
    await page.close()
  }
  assert.equal(new Set(evidence.themeChecks.map(check => check.navBackground)).size, 4, 'Each feature theme should give the top navigation its own background color')

  const navigationPage = await newPage()
  await navigationPage.goto(base, { waitUntil: 'networkidle' })
  await verifyNavigationAndHistory(navigationPage)
  await navigationPage.close()

  for (const feature of features.filter(item => item.delay)) {
    const timerPage = await newPage()
    const otherFeature = features.find(item => item.id !== feature.id)
    await verifyDemoTimerStops(timerPage, feature, otherFeature)
    await timerPage.close()
  }

  const agentTimerPage = await newPage()
  await verifyAgentAutomaticSequence(agentTimerPage)
  await agentTimerPage.close()

  const feedbackTimerPage = await newPage()
  await verifyFeedbackAutomaticLoop(feedbackTimerPage)
  await feedbackTimerPage.close()

  const evidenceTimerPage = await newPage({
    viewport: { width: 1331, height: 871 },
    deviceScaleFactor: 1.5,
  })
  await verifyEvidenceAutomaticLoop(evidenceTimerPage)
  await evidenceTimerPage.close()

  const guardPage = await newPage()
  await guardPage.goto(base + '/learning/new', { waitUntil: 'networkidle' })
  await guardPage.waitForURL(url => url.pathname === '/' && url.searchParams.get('login') === '1')
  assert.equal(new URL(guardPage.url()).searchParams.get('redirect'), '/learning/new')
  assert.equal(await guardPage.getByRole('dialog', { name: '账号登录', exact: true }).count(), 1, 'Protected onboarding route should open login')
  await guardPage.goto(base + '/learning/new', { waitUntil: 'networkidle' })
  await guardPage.waitForURL(url => url.pathname === '/' && url.searchParams.get('login') === '1')
  assert.equal(new URL(guardPage.url()).searchParams.get('redirect'), '/learning/new')
  evidence.routes.push({ protectedRoute: '/learning/new', anonymousGuard: 'PASS', redirect: '/learning/new' })
  await guardPage.close()

  assert.deepEqual(api.writes, [], 'Showcase interactions must not issue API writes')
  assert.deepEqual(errors, [], 'Browser page errors')
  assert.equal(layoutFailures.length, 0, `Viewport geometry failures: ${JSON.stringify(layoutFailures)}`)
  evidence.status = 'PASS'
  console.log(`Feature showcase browser PASS: ${evidence.layoutChecks.length} viewport checks, ${evidence.screenshots.length} screenshots, ${evidence.interactions.length} interaction checks; ${reportDir}`)
} catch (error) {
  evidence.status = 'FAIL'
  evidence.failure = error.stack
  throw error
} finally {
  evidence.api = { requests: api.requests, writes: api.writes }
  writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify(evidence, null, 2))
  await browser?.close()
  if (server.listening) await new Promise(resolve => server.close(resolve))
}
