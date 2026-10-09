import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(root, 'dist')
const reportDir = path.join(root, 'tests/test-results/landing-ui')
if (!existsSync(path.join(dist, 'index.html'))) throw new Error('Run npm --prefix frontend run build first')
mkdirSync(reportDir, { recursive: true })
const state = { user: null, loginOutcome: 'reject', registerOutcome: 'reject', logins: [], registrations: [] }
const fixtureUser = { user_id: 'ui_fixture_user', username: 'ui_fixture', display_name: '界面验收用户' }
const fixturePassword = 'fixture-password-123'
const errors = []
const evidence = { viewportChecks: [], screenChecks: [], themeChecks: [], interactions: [], contrastChecks: [], accessScrollChecks: [], portalAnimationChecks: [], screenshots: [], feedbackPauseScrollChecks: [], desktopScrollChecks: [], errors }
const screens = [
  { id: 'overview', label: '学习概览' },
  { id: 'features', label: '平台能力', theme: 'capabilities' },
  { id: 'multi-agent', label: '协作星图', feature: 'agents' },
  { id: 'evidence', label: '证据档案', feature: 'evidence' },
  { id: 'learning-path', label: '成长航线', feature: 'path' },
  { id: 'feedback-loop', label: '反馈进阶', feature: 'feedback' },
]
evidence.screens = screens.map(({ id, label, feature, theme }) => ({ id, label, feature: feature || null, theme: theme || feature || 'home' }))

// This isolated fixture server never proxies authentication to the running backend.
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://fixture')
  const json = (value, status = 200) => {
    res.writeHead(status, { 'content-type': 'application/json' })
    res.end(JSON.stringify(value))
  }
  if (url.pathname === '/api/auth/me') return json({ user: state.user })
  if (['/api/auth/login', '/api/auth/register'].includes(url.pathname)) {
    let body = ''
    for await (const chunk of req) body += chunk
    const registration = url.pathname.endsWith('/register')
    const records = registration ? state.registrations : state.logins
    records.push(JSON.parse(body))
    await new Promise(resolve => setTimeout(resolve, 200))
    if ((registration ? state.registerOutcome : state.loginOutcome) === 'reject') {
      return json({ detail: registration ? '该用户名已存在' : '用户名或密码错误' }, registration ? 409 : 401)
    }
    state.user = fixtureUser
    return json({ user: fixtureUser })
  }
  if (url.pathname === '/api/profiles/') return json({ items: [] })
  if (url.pathname === '/api/knowledge/domains') return json({ domains: [] })
  if (url.pathname.startsWith('/api/')) return json({ items: [], resources: [] })
  const candidate = path.resolve(dist, `.${decodeURIComponent(url.pathname)}`)
  const safe = candidate.startsWith(dist + path.sep) && existsSync(candidate)
  const file = safe && path.extname(candidate) ? candidate : path.join(dist, 'index.html')
  const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png' }
  res.setHeader('content-type', types[path.extname(file)] || 'application/octet-stream')
  res.end(readFileSync(file))
})

let browser
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`

async function stable(page) {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForFunction(() => [...document.querySelectorAll('.landing-page, .access-overlay')].every(el =>
    !el.getAnimations({ subtree: true }).some(animation => {
      const target = animation.effect?.target
      const workbench = target?.closest?.('.feedback-workbench')
      if (workbench?.dataset.playing === 'true' && target.closest('.feedback-sequence, .feedback-progress')) return false
      if (animation.playState !== 'running' && animation.playState !== 'pending') return false
      return Number.isFinite(animation.effect?.getComputedTiming().endTime)
    }),
  ))
}

async function screenshot(page, filename) {
  await stable(page)
  const buffer = await page.screenshot({ path: path.join(reportDir, filename) })
  evidence.screenshots.push({ filename, width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20), viewport: page.viewportSize() })
}

async function geometry(page, label) {
  const metrics = await page.evaluate(() => {
    const root = document.querySelector('.landing-page')
    const dialog = document.querySelector('.access-dialog')
    const body = dialog?.querySelector('.el-dialog__body')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      rootWidth: root.clientWidth, rootScrollWidth: root.scrollWidth,
      dialog: dialog ? { width: dialog.clientWidth, scrollWidth: dialog.scrollWidth, left: dialog.getBoundingClientRect().left, right: dialog.getBoundingClientRect().right } : null,
      body: body ? { width: body.clientWidth, scrollWidth: body.scrollWidth } : null,
    }
  })
  assert.ok(metrics.documentWidth <= metrics.viewport.width + 1, `${label}: document horizontal overflow`)
  assert.ok(metrics.rootScrollWidth <= metrics.rootWidth + 1, `${label}: homepage horizontal overflow`)
  if (metrics.dialog) {
    assert.ok(metrics.dialog.left >= -1 && metrics.dialog.right <= metrics.viewport.width + 1, `${label}: dialog outside viewport`)
    assert.ok(metrics.body.scrollWidth <= metrics.body.width + 1, `${label}: dialog content overflow`)
  }
  evidence.viewportChecks.push({ label, ...metrics })
}

async function screenSettled(page, index) {
  await page.waitForFunction(index => {
    const scroller = document.querySelector('.landing-main')
    const screen = document.querySelector(`#${['overview', 'features', 'multi-agent', 'evidence', 'learning-path', 'feedback-loop'][index]}`)
    return Math.abs(scroller.scrollTop - screen.offsetTop) < 2
  }, index)
  await stable(page)
}

async function feedbackScreenAligned(page, label) {
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

async function fullScreenGeometry(page, label, index) {
  const metrics = await page.evaluate(index => {
    const rect = el => {
      const box = el.getBoundingClientRect()
      return { top: box.top, bottom: box.bottom, height: box.height }
    }
    const main = document.querySelector('.landing-main')
    const ids = ['overview', 'features', 'multi-agent', 'evidence', 'learning-path', 'feedback-loop']
    const screen = document.querySelector(`#${ids[index]}`)
    const selectors = index === 0
      ? '.hero-content, .learning-visual, .screen-cue'
      : index === 1
        ? '.section-heading, .feature-card, .capability-art, .capability-art svg, .feature-invitation, .back-to-overview, .feature-invitation .primary-action, .feature-section > .screen-cue'
        : '.feature-intro, .feature-scene'
    const nextScreen = document.querySelector(`#${ids[index + 1]}`)
    return {
      paged: document.querySelector('.landing-page').classList.contains('is-paged'),
      viewportHeight: innerHeight,
      main: rect(main), screen: rect(screen),
      screenId: screen.id,
      nextScreenTop: nextScreen?.getBoundingClientRect().top ?? null,
      visibleItems: [...screen.querySelectorAll(selectors)].map(el => ({ selector: el.className, ...rect(el) })),
      currentPage: document.querySelector('.screen-pagination button[aria-current]')?.getAttribute('aria-label'),
    }
  }, index)
  assert.ok(metrics.paged, `${label}: desktop should use full-screen mode`)
  assert.ok(Math.abs(metrics.main.bottom - metrics.viewportHeight) < 2, `${label}: viewport not filled`)
  assert.ok(Math.abs(metrics.screen.height - metrics.main.height) < 2, `${label}: screen height differs from viewport`)
  assert.ok(Math.abs(metrics.screen.top - metrics.main.top) < 2, `${label}: screen not aligned`)
  if (metrics.nextScreenTop !== null) assert.ok(metrics.nextScreenTop >= metrics.main.bottom - 1, `${label}: next screen peeks into ${metrics.screenId}`)
  for (const item of metrics.visibleItems) {
    assert.ok(item.top >= metrics.main.top - 1 && item.bottom <= metrics.main.bottom + 1, `${label}: ${item.selector} clipped`)
  }
  assert.equal(metrics.currentPage, `第 ${index + 1} 屏：${screens[index].label}`, `${label}: current-page state incorrect`)
  evidence.screenChecks.push({ label, ...metrics })
}

async function reachable(locator) {
  await locator.scrollIntoViewIfNeeded()
  const hit = await locator.evaluate(el => {
    const rect = el.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    const target = document.elementFromPoint(x, y)
    return x >= 0 && x < innerWidth && y >= 0 && y < innerHeight && target && (target === el || el.contains(target))
  })
  assert.ok(hit, 'Control is clipped or obscured')
}

async function newPage(options = {}) {
  const page = await browser.newPage({ viewport: { width: 1257, height: 860 }, deviceScaleFactor: 1.5, ...options })
  page.on('pageerror', error => errors.push(error.message))
  return page
}

async function contrast(page, selector, minimum = 4.5) {
  const result = await page.locator(selector).first().evaluate(el => {
    const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
    const luminance = values => values.map(value => {
      const channel = value / 255
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
    }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
    const style = getComputedStyle(el)
    let background = style.backgroundColor
    let parent = el
    while (background === 'rgba(0, 0, 0, 0)' && parent.parentElement) {
      parent = parent.parentElement
      background = getComputedStyle(parent).backgroundColor
    }
    const foregroundL = luminance(rgb(style.color))
    const backgroundL = luminance(rgb(background))
    return { foreground: style.color, background, ratio: (Math.max(foregroundL, backgroundL) + .05) / (Math.min(foregroundL, backgroundL) + .05) }
  })
  assert.ok(result.ratio >= minimum, `${selector}: contrast ${result.ratio.toFixed(2)} below ${minimum}`)
  evidence.contrastChecks.push({ selector, ...result })
}

async function contrastOnSurface(page, foregroundSelector, surfaceSelector, label, pseudo = null, minimum = 4.5) {
  const result = await page.locator(foregroundSelector).first().evaluate((foreground, args) => {
    const parseColor = value => {
      if (value.startsWith('#')) {
        const hex = value.slice(1)
        const expanded = hex.length <= 4 ? [...hex].map(char => char + char).join('') : hex
        return { r: parseInt(expanded.slice(0, 2), 16), g: parseInt(expanded.slice(2, 4), 16), b: parseInt(expanded.slice(4, 6), 16), a: expanded.length >= 8 ? parseInt(expanded.slice(6, 8), 16) / 255 : 1 }
      }
      const channels = (value.match(/[\d.]+/g) || []).map(Number)
      if (channels.length < 3) throw new Error(`Unsupported computed color: ${value}`)
      return { r: channels[0], g: channels[1], b: channels[2], a: channels[3] ?? 1 }
    }
    const composite = (front, back) => ({
      r: front.r * front.a + back.r * (1 - front.a),
      g: front.g * front.a + back.g * (1 - front.a),
      b: front.b * front.a + back.b * (1 - front.a),
      a: 1,
    })
    const luminance = color => [color.r, color.g, color.b].map(channel => {
      const value = channel / 255
      return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4
    }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
    const ratio = (left, right) => (Math.max(luminance(left), luminance(right)) + .05) / (Math.min(luminance(left), luminance(right)) + .05)
    const surface = document.querySelector(args.surfaceSelector)
    if (!surface) throw new Error(`Missing contrast surface: ${args.surfaceSelector}`)
    const style = getComputedStyle(surface)
    const backgroundColor = parseColor(style.backgroundColor)
    const imageColors = [...style.backgroundImage.matchAll(/rgba?\([^)]*\)|#[0-9a-f]{3,8}/gi)].map(match => parseColor(match[0]))
    const opaqueBase = [...imageColors].reverse().find(color => color.a >= .999) || (backgroundColor.a >= .999 ? backgroundColor : null)
    if (!opaqueBase) throw new Error(`No opaque base color on ${args.surfaceSelector}: ${style.backgroundImage} / ${style.backgroundColor}`)
    // Include every gradient stop composited over its opaque base so a favorable
    // midpoint or a transparent ancestor cannot hide a low-contrast endpoint.
    const backgrounds = style.backgroundImage === 'none'
      ? [backgroundColor]
      : [opaqueBase, ...imageColors.map(color => composite(color, opaqueBase))]
    const textStyle = getComputedStyle(foreground, args.pseudo)
    const foregroundColor = parseColor(textStyle.color)
    const checks = backgrounds.map(background => {
      const visibleForeground = composite(foregroundColor, background)
      return { background, ratio: ratio(visibleForeground, background) }
    })
    const worst = checks.reduce((current, item) => item.ratio < current.ratio ? item : current)
    const lightestBackground = Math.min(...backgrounds.map(luminance))
    return {
      foreground: textStyle.color,
      surface: args.surfaceSelector,
      backgroundImage: style.backgroundImage,
      backgroundColor: style.backgroundColor,
      endpoints: backgrounds,
      worstBackground: worst.background,
      ratio: worst.ratio,
      minimumBackgroundLuminance: lightestBackground,
    }
  }, { surfaceSelector, pseudo })
  assert.ok(result.ratio >= minimum, `${label}: worst gradient endpoint contrast ${result.ratio.toFixed(2)} below ${minimum}`)
  evidence.contrastChecks.push({ selector: foregroundSelector, label, ...result })
  return result
}

async function accessGeometry(page, label) {
  const result = await page.evaluate(() => {
    const rect = selector => {
      const element = document.querySelector(selector)
      if (!element) return null
      const box = element.getBoundingClientRect()
      return { x: box.x, y: box.y, top: box.top, right: box.right, bottom: box.bottom, left: box.left, width: box.width, height: box.height }
    }
    const dialog = document.querySelector('.access-dialog')
    const body = dialog?.querySelector('.el-dialog__body')
    const layout = dialog?.querySelector('.access-layout')
    const scroller = dialog?.querySelector('.access-form-scroll')
    const style = element => element ? getComputedStyle(element) : null
    const bodyStyle = style(body), layoutStyle = style(layout), scrollerStyle = style(scroller)
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight, scrollTop: document.scrollingElement?.scrollTop ?? 0 },
      windowScrollY: scrollY,
      dialogContentHeight: dialog?.clientHeight ?? null,
      landing: { width: document.querySelector('.landing-page')?.clientWidth ?? null, scrollWidth: document.querySelector('.landing-page')?.scrollWidth ?? null, scrollTop: document.querySelector('.landing-main')?.scrollTop ?? null },
      dialog: rect('.access-dialog'),
      body: rect('.access-dialog .el-dialog__body'),
      layout: rect('.access-dialog .access-layout'),
      story: rect('.access-dialog .access-story'),
      art: rect('.access-dialog .access-portal-art'),
      svg: rect('.access-dialog .portal-art'),
      storyText: ['.access-brand', '.access-story-copy', '.access-benefits', '.access-story-footer'].map(selector => ({ selector, rect: rect(`.access-dialog ${selector}`) })),
      formSide: rect('.access-dialog .access-form-side'),
      formScroll: rect('.access-dialog .access-form-scroll'),
      close: rect('.access-dialog .modal-close'),
      submit: rect('.access-dialog .access-submit'),
      scroll: scroller ? { top: scroller.scrollTop, height: scroller.scrollHeight, clientHeight: scroller.clientHeight, width: scroller.scrollWidth, clientWidth: scroller.clientWidth } : null,
      bodyScrollTop: body?.scrollTop ?? null,
      layoutScrollTop: layout?.scrollTop ?? null,
      bodyOverflowY: bodyStyle?.overflowY ?? null,
      layoutOverflowY: layoutStyle?.overflowY ?? null,
      scrollerOverflowY: scrollerStyle?.overflowY ?? null,
      scrollerOverflowX: scrollerStyle?.overflowX ?? null,
      storyDisplay: style(document.querySelector('.access-dialog .access-story'))?.display ?? null,
    }
  })
  assert.ok(result.dialog, `${label}: access dialog is missing`)
  assert.ok(result.dialog.left >= -1 && result.dialog.right <= result.viewport.width + 1, `${label}: dialog is outside the viewport`)
  assert.ok(result.document.width <= result.viewport.width + 1, `${label}: document has horizontal overflow`)
  assert.ok(result.landing.scrollWidth <= result.landing.width + 1, `${label}: landing page has horizontal overflow`)
  assert.ok(result.body.width <= result.dialog.width + 1, `${label}: dialog body overflows horizontally`)
  assert.ok(result.scroll, `${label}: .access-form-scroll is missing`)
  assert.ok(result.scroll.width <= result.scroll.clientWidth + 1, `${label}: form scroller overflows horizontally`)
  assert.ok(['hidden', 'clip'].includes(result.bodyOverflowY), `${label}: dialog body must not own vertical scrolling (${result.bodyOverflowY})`)
  assert.ok(['hidden', 'clip'].includes(result.layoutOverflowY), `${label}: dialog layout must not own vertical scrolling (${result.layoutOverflowY})`)
  assert.ok(['auto', 'scroll'].includes(result.scrollerOverflowY), `${label}: right form area must own vertical scrolling (${result.scrollerOverflowY})`)
  assert.ok(['auto', 'scroll', 'hidden', 'clip'].includes(result.scrollerOverflowX), `${label}: right form area has unsupported horizontal overflow (${result.scrollerOverflowX})`)
  const isCompact = result.viewport.width <= 820 || result.viewport.height <= 679
  const expectedHeight = Math.min(isCompact ? 660 : 760, result.viewport.height - (isCompact ? 24 : 64))
  assert.ok(Math.abs(result.dialog.height - expectedHeight) < 2, `${label}: dialog height should match its viewport cap (${expectedHeight}px), got ${result.dialog.height}px`)
  assert.ok(Math.abs(result.body.height - result.dialogContentHeight) < 2, `${label}: dialog body should fill the dialog content box (${result.body.height}px body, ${result.dialogContentHeight}px content)`)
  assert.ok(Math.abs(result.layout.height - result.body.height) < 2, `${label}: dialog layout should fill the body`)
  if (isCompact) assert.equal(result.storyDisplay, 'none', `${label}: compact dialog should hide the left story column`)
  else {
    assert.ok(result.story?.width > 0 && result.svg?.width > 0, `${label}: desktop story artwork should be visible`)
    for (const item of result.storyText) {
      if (!item.rect) continue
      const overlaps = result.art.left < item.rect.right - 1 && result.art.right > item.rect.left + 1 && result.art.top < item.rect.bottom - 1 && result.art.bottom > item.rect.top + 1
      assert.equal(overlaps, false, `${label}: SVG illustration overlaps ${item.selector}`)
    }
  }
  evidence.accessScrollChecks.push({ label, stage: 'geometry', ...result })
  return result
}

async function inputSurfaceCheck(page, label) {
  const username = page.locator('#signin-username')
  await username.focus()
  await page.waitForFunction(() => {
    const input = document.querySelector('#signin-username')
    return document.activeElement === input && input?.closest('.el-input__wrapper')?.classList.contains('is-focus')
  })
  const focused = await username.evaluate(input => {
    const inner = getComputedStyle(input)
    const wrapper = input.closest('.el-input__wrapper')
    const outer = getComputedStyle(wrapper)
    return {
      borderWidth: inner.borderTopWidth,
      outlineStyle: inner.outlineStyle,
      shadow: inner.boxShadow,
      backgroundColor: inner.backgroundColor,
      wrapperFocused: wrapper.classList.contains('is-focus'),
      wrapperShadow: outer.boxShadow,
      wrapperBackground: outer.backgroundColor,
    }
  })
  assert.equal(focused.borderWidth, '0px', `${label}: input inner border must be removed`)
  assert.equal(focused.outlineStyle, 'none', `${label}: input inner outline must be removed`)
  assert.equal(focused.shadow, 'none', `${label}: input inner shadow must be removed`)
  assert.equal(focused.backgroundColor, 'rgba(0, 0, 0, 0)', `${label}: input inner fill must remain transparent`)
  assert.equal(focused.wrapperFocused, true, `${label}: focus state must be on the outer input wrapper`)
  assert.notEqual(focused.wrapperShadow, 'none', `${label}: outer input wrapper needs a visible focus ring`)

  await username.blur()
  await page.waitForFunction(() => !document.querySelector('#signin-username')?.closest('.el-input__wrapper')?.classList.contains('is-focus'))
  const ordinary = await username.evaluate(input => ({ backgroundColor: getComputedStyle(input).backgroundColor, placeholder: getComputedStyle(input, '::placeholder').color }))
  assert.equal(ordinary.backgroundColor, 'rgba(0, 0, 0, 0)', `${label}: ordinary input fill must be transparent`)
  evidence.accessScrollChecks.push({ label, stage: 'input surface and focus', focused, ordinary })
  return ordinary
}

async function profileScrollCheck(page, label) {
  const dialog = page.getByRole('dialog', { name: '注册账号', exact: true })
  const scroller = page.locator('.access-form-scroll')
  const details = page.locator('.optional-details')
  const close = page.locator('.modal-close')
  await dialog.waitFor()
  await assertNoPauseControls(page, label)
  await scroller.evaluate(element => element.scrollTo({ top: 0, behavior: 'instant' }))
  await details.locator('summary').scrollIntoViewIfNeeded()
  const before = await accessGeometry(page, `${label}/before profile expansion`)
  assert.ok(before.scroll, `${label}: .access-form-scroll is missing`)
  await details.locator('summary').click()
  await page.waitForFunction(() => document.querySelector('.optional-details')?.open === true)
  const expanded = await accessGeometry(page, `${label}/after profile expansion`)
  assert.ok(expanded.scroll.height > before.scroll.height, `${label}: profile fields did not increase right-side scrollHeight`)
  const fixedSelectors = ['dialog', 'body', 'layout', 'story', 'art', 'svg', 'formSide', 'formScroll', 'close']
  for (const key of fixedSelectors) {
    const prior = before[key]
    const next = expanded[key]
    if (prior === null || next === null) {
      assert.equal(next, prior, `${label}: ${key} visibility changed after profile expansion`)
      continue
    }
    for (const edge of ['x', 'y', 'top', 'right', 'bottom', 'left', 'width', 'height']) {
      assert.ok(Math.abs(next[edge] - prior[edge]) < 1, `${label}: ${key}.${edge} changed after profile expansion (${prior[edge]} -> ${next[edge]})`)
    }
  }
  assert.equal(expanded.document.scrollTop, before.document.scrollTop, `${label}: page scroll changed after profile expansion`)
  assert.equal(expanded.windowScrollY, before.windowScrollY, `${label}: window scroll changed after profile expansion`)
  assert.equal(expanded.landing.scrollTop, before.landing.scrollTop, `${label}: landing background moved after profile expansion`)
  assert.equal(expanded.bodyScrollTop, before.bodyScrollTop, `${label}: dialog body scrolled after profile expansion`)
  assert.equal(expanded.layoutScrollTop, before.layoutScrollTop, `${label}: dialog layout scrolled after profile expansion`)

  await scroller.evaluate(element => element.scrollTo({ top: 0, behavior: 'instant' }))
  const top = await scroller.evaluate(element => element.scrollTop)
  await scroller.evaluate(element => element.scrollTo({ top: element.scrollHeight, behavior: 'instant' }))
  await page.waitForFunction(() => {
    const element = document.querySelector('.access-form-scroll')
    return element && element.scrollTop > 0 && element.scrollTop + element.clientHeight >= element.scrollHeight - 1
  })
  const atBottom = await accessGeometry(page, `${label}/right side scrolled to bottom`)
  assert.ok(atBottom.scroll.top > top, `${label}: right-side scrollTop did not move`)
  assert.ok(atBottom.scroll.top + atBottom.scroll.clientHeight >= atBottom.scroll.height - 1, `${label}: right-side form did not reach its bottom`)
  assert.equal(atBottom.document.scrollTop, before.document.scrollTop, `${label}: page scrolled while moving within the form`)
  assert.equal(atBottom.windowScrollY, before.windowScrollY, `${label}: window scrolled while moving within the form`)
  assert.equal(atBottom.landing.scrollTop, before.landing.scrollTop, `${label}: landing background moved while moving within the form`)
  assert.equal(atBottom.bodyScrollTop, before.bodyScrollTop, `${label}: dialog body moved while moving within the form`)
  assert.equal(atBottom.layoutScrollTop, before.layoutScrollTop, `${label}: dialog layout moved while moving within the form`)
  for (const edge of ['x', 'y', 'top', 'right', 'bottom', 'left', 'width', 'height']) {
    assert.ok(Math.abs(atBottom.close[edge] - expanded.close[edge]) < 1, `${label}: close button moved with the right-side scroll (${edge})`)
  }
  await reachable(close)
  await reachable(dialog.locator('.access-submit'))
  await screenshot(page, `register-expanded-${label.replace(/[^a-z0-9-]+/gi, '-')}.png`)
  evidence.accessScrollChecks.push({ label, stage: 'profile expansion and independent scroll', before, expanded, atBottom })
}

async function assertNoPauseControls(page, label) {
  const count = await page.locator('.access-dialog button').evaluateAll(buttons => buttons.filter(button => /暂停|播放动画|停止动画/.test(`${button.getAttribute('aria-label') || ''} ${button.innerText}`)).length)
  assert.equal(count, 0, `${label}: auth dialog must not expose a manual animation control`)
  return count
}

async function portalMotion(page, label) {
  const portal = page.locator('.portal-art')
  assert.equal(await portal.count(), 1, `${label}: the login illustration should be present once`)
  assert.equal(await portal.locator('button, [role="button"]').count(), 0, `${label}: animated illustration must not add a pause control`)
  await assertNoPauseControls(page, label)
  const sample = await portal.evaluate(svg => {
    const core = svg.querySelector('.portal-core')
    const tracer = svg.querySelector('.portal-tracer')
    const whiteOrbit = svg.querySelector('ellipse[rx="142"][ry="103"]')
    const outerOrbit = svg.querySelector('ellipse[rx="157"][ry="112"]')
    const animationsFor = element => [...document.getAnimations({ subtree: true })]
      .filter(animation => animation.effect?.target === element)
      .map(animation => ({ state: animation.playState, endTime: animation.effect.getComputedTiming().endTime, name: getComputedStyle(element).animationName }))
    const coreStyle = core ? getComputedStyle(core) : null
    const tracerStyle = tracer ? getComputedStyle(tracer) : null
    return {
      active: svg.classList.contains('is-active'),
      hasCrystal: Boolean(svg.querySelector('.portal-crystal')),
      core: core ? {
        transform: coreStyle.transform,
        animations: animationsFor(core),
        forbiddenGeometry: core.querySelectorAll('rect, path, polygon, polyline').length,
        circles: [...core.querySelectorAll('circle')].map(circle => ({ cx: Number(circle.getAttribute('cx')), cy: Number(circle.getAttribute('cy')), r: Number(circle.getAttribute('r')) })),
        logo: (() => {
          const image = core.querySelector('image')
          return image ? { x: Number(image.getAttribute('x')), y: Number(image.getAttribute('y')), width: Number(image.getAttribute('width')), height: Number(image.getAttribute('height')) } : null
        })(),
      } : null,
      tracer: tracer ? { offsetDistance: tracerStyle.offsetDistance, offsetPath: tracerStyle.offsetPath, parentTransform: tracer.parentElement?.getAttribute('transform'), animations: animationsFor(tracer) } : null,
      whiteOrbit: whiteOrbit ? { cx: Number(whiteOrbit.getAttribute('cx')), cy: Number(whiteOrbit.getAttribute('cy')), rx: Number(whiteOrbit.getAttribute('rx')), ry: Number(whiteOrbit.getAttribute('ry')), transform: whiteOrbit.getAttribute('transform'), stroke: getComputedStyle(whiteOrbit).stroke } : null,
      outerOrbit: outerOrbit ? { cx: Number(outerOrbit.getAttribute('cx')), cy: Number(outerOrbit.getAttribute('cy')), rx: Number(outerOrbit.getAttribute('rx')), ry: Number(outerOrbit.getAttribute('ry')), transform: outerOrbit.getAttribute('transform'), stroke: outerOrbit.getAttribute('stroke') } : null,
      pauseButtons: svg.querySelectorAll('button, [role="button"]').length,
    }
  })
  assert.equal(sample.active, true, `${label}: auth-visible illustration should be active without user input`)
  assert.equal(sample.hasCrystal, false, `${label}: open orbit design must not contain the removed cube`)
  assert.ok(sample.core?.animations.some(animation => animation.state === 'running' && animation.endTime === Infinity), `${label}: portal core should have a running infinite CSS animation`)
  assert.ok(sample.tracer?.animations.some(animation => animation.state === 'running' && animation.endTime === Infinity), `${label}: tracer should have a running infinite CSS animation`)
  assert.notEqual(sample.tracer.offsetPath, 'none', `${label}: tracer needs a CSS offset path`)
  assert.deepEqual(sample.whiteOrbit, { cx: 240, cy: 167, rx: 142, ry: 103, transform: 'rotate(30 240 167)', stroke: 'rgb(255, 255, 255)' }, `${label}: the moving tracer must share the white outer ellipse path and rotation`)
  assert.deepEqual(sample.outerOrbit, { cx: 240, cy: 167, rx: 157, ry: 112, transform: 'rotate(-28 240 167)', stroke: 'url(#access-orbit)' }, `${label}: open secondary track must remain a separate expanded orbit`)
  assert.equal(sample.tracer.parentTransform, sample.whiteOrbit.transform, `${label}: tracer and white orbit must rotate together`)
  const pathNumbers = (sample.tracer.offsetPath.match(/-?[\d.]+/g) || []).map(Number)
  assert.deepEqual(pathNumbers, [98, 167, 142, 103, 0, 1, 1, 382, 167, 142, 103, 0, 1, 1, 98, 167], `${label}: tracer path must be a closed ellipse matching the white orbit; matching endpoints prevent a loop seam jump`)
  assert.equal(sample.core.forbiddenGeometry, 0, `${label}: logo core must not contain cube faces, a white card or a coarse crossing path`)
  assert.deepEqual(sample.core.circles, [{ cx: 240, cy: 167, r: 98 }, { cx: 240, cy: 167, r: 76 }, { cx: 240, cy: 167, r: 84 }], `${label}: core should use the centered halo and two fine circles`)
  assert.deepEqual(sample.core.logo, { x: 198, y: 122, width: 84, height: 84 }, `${label}: brand logo should stay independently centered without a backing card`)
  const logoCornerRadius = Math.hypot(sample.core.logo.width, sample.core.logo.height) / 2 + Math.hypot(sample.core.logo.x + sample.core.logo.width / 2 - 240, sample.core.logo.y + sample.core.logo.height / 2 - 167) + 5
  assert.ok(logoCornerRadius < sample.core.circles[1].r, `${label}: logo must remain inside the fine core circle throughout its 5px float`)
  assert.ok(Math.min(sample.whiteOrbit.rx, sample.whiteOrbit.ry) > sample.core.circles[2].r + 5, `${label}: white tracer orbit must clear the moving core ring`)
  assert.equal(sample.pauseButtons, 0)
  return sample
}

try {
  // Missing browser is an error, never a silently skipped acceptance gate.
  browser = await chromium.launch(browserOptions('LANDING_BROWSER_CHANNEL'))
  const viewports = [
    { name: 'desktop', width: 1257, height: 860, scale: 1.5 },
    { name: 'wide', width: 1440, height: 900 },
    { name: 'compact', width: 1024, height: 768 },
    { name: 'panoramic', width: 2466, height: 1381 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'narrow', width: 375, height: 812 },
    { name: 'short', width: 1257, height: 520 },
    // 200% browser zoom halves the available CSS layout viewport of a 1440x860 desktop.
    { name: 'zoom-200-layout', width: 720, height: 430, scale: 2 },
  ]
  for (const viewport of viewports) {
    const page = await newPage({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale || 1 })
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByRole('heading', { level: 1 }).waitFor()
    assert.equal(await page.locator('.landing-screen').count(), screens.length, `${viewport.name}: homepage should contain six screens`)
    assert.equal(await page.locator('h1').count(), 1, `${viewport.name}: homepage should have a single h1`)
    for (const screen of screens.slice(2)) {
      const panel = page.locator(`#${screen.id}.showcase-panel[data-feature="${screen.feature}"]`)
      assert.equal(await panel.count(), 1, `${viewport.name}: missing ${screen.feature} showcase panel`)
      assert.ok(await panel.locator('h2').count(), `${viewport.name}: ${screen.feature} panel should use h2 headings`)
    }
    assert.equal(await page.locator('.screen-pagination button').count(), 6, `${viewport.name}: pagination should expose six screens`)
    await geometry(page, `home/${viewport.name}`)
    const paged = ['desktop', 'wide', 'compact', 'panoramic'].includes(viewport.name)
    for (let index = 0; index < screens.length; index++) {
      if (index > 0) await page.goto(`${base}/#${screens[index].id}`, { waitUntil: 'networkidle' })
      if (screens[index].id === 'feedback-loop') {
        const playback = page.locator('#feedback-loop .feedback-playback')
        await playback.waitFor({ state: 'visible' })
        await feedbackScreenAligned(page, `${viewport.name}/before pause`)
        const beforePause = await page.evaluate(() => {
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
        await feedbackScreenAligned(page, `${viewport.name}/after pause`)
        const afterPause = await page.evaluate(() => {
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
        assert.ok(Math.abs(beforePause.scrollTop - beforePause.offsetTop) < 2 && Math.abs(beforePause.panelTop - beforePause.mainTop) < 2, `${viewport.name}: feedback should align before pausing: ${JSON.stringify(beforePause)}`)
        assert.ok(Math.abs(afterPause.scrollTop - afterPause.offsetTop) < 2 && Math.abs(afterPause.panelTop - afterPause.mainTop) < 2, `${viewport.name}: pausing should preserve active-screen alignment: ${JSON.stringify(afterPause)}`)
        assert.equal(afterPause.offsetTop, beforePause.offsetTop, `${viewport.name}: pausing must not change the feedback section offset`)
        assert.equal(afterPause.activeElement, beforePause.activeElement, `${viewport.name}: pausing for a screenshot must not move keyboard focus`)
        evidence.feedbackPauseScrollChecks.push({ viewport: viewport.name, before: beforePause, after: afterPause, source: 'synthetic click event for screenshot/stability preparation' })
        await page.locator('#feedback-loop .feedback-stage[data-feedback-step="1"]').evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
      }
      await screenSettled(page, index)
      const activeTheme = await page.evaluate(() => {
        const root = document.querySelector('.landing-page')
        const nav = document.querySelector('.landing-nav')
        const activePanel = document.querySelector(`${location.hash}.showcase-panel[data-feature]`) || (location.hash === '#features' ? document.querySelector('#features.feature-section') : null)
        const currentPagination = document.querySelector('.screen-pagination button[aria-current]')
        const colorProbe = document.createElement('span')
        document.body.append(colorProbe)
        const resolveColor = value => {
          colorProbe.style.color = value
          return getComputedStyle(colorProbe).color
        }
        const resolvedAccent = resolveColor(getComputedStyle(root).getPropertyValue('--sc-accent').trim())
        const laterAccents = ['multi-agent', 'evidence', 'learning-path', 'feedback-loop'].map(id => resolveColor(getComputedStyle(document.querySelector(`#${id}`)).getPropertyValue('--sc-accent').trim()))
        colorProbe.remove()
        return {
          name: root?.dataset.theme || null,
          navBackground: nav ? getComputedStyle(nav).backgroundColor : null,
          panelBackground: activePanel ? getComputedStyle(activePanel).backgroundColor : null,
          accent: resolvedAccent,
          currentPaginationColor: currentPagination ? getComputedStyle(currentPagination).color : null,
          currentPaginationMarker: currentPagination ? getComputedStyle(currentPagination.querySelector('i')).backgroundColor : null,
          laterAccents,
        }
      })
      const expectedTheme = screens[index].theme || screens[index].feature || 'home'
      assert.equal(activeTheme.name, expectedTheme, `${viewport.name}/${screens[index].id}: active theme should follow the current screen`)
      if (screens[index].id === 'features') {
        assert.equal(activeTheme.navBackground, activeTheme.panelBackground, `${viewport.name}/features: top navigation background should follow the capabilities theme`)
        assert.equal(activeTheme.currentPaginationColor, activeTheme.accent, `${viewport.name}/features: active pagination color should follow the capabilities accent`)
        assert.equal(activeTheme.currentPaginationMarker, activeTheme.accent, `${viewport.name}/features: active pagination marker should follow the capabilities accent`)
        assert.equal(new Set([activeTheme.accent, ...activeTheme.laterAccents]).size, 5, `${viewport.name}/features: capabilities accent should stay distinct from all later themes`)
        const art = await page.locator('#features .capability-art svg').evaluateAll(elements => elements.map(svg => {
          const rect = svg.getBoundingClientRect()
          const style = getComputedStyle(svg)
          return { width: rect.width, height: rect.height, display: style.display, visibility: style.visibility, graphics: svg.querySelectorAll('path, circle, ellipse, rect').length }
        }))
        assert.equal(art.length, 4, `${viewport.name}/features: all four capability diagrams should render`)
        for (const [index, diagram] of art.entries()) {
          assert.ok(diagram.width > 0 && diagram.height > 0 && diagram.display !== 'none' && diagram.visibility !== 'hidden' && diagram.graphics > 0, `${viewport.name}/features: capability diagram ${index + 1} is not visible`)
        }
        if (viewport.name === 'desktop') {
          await contrast(page, '#features .feature-card p', 4.5)
          await contrast(page, '#features .feature-invitation .primary-action', 4.5)
        }
      }
      if (screens[index].feature) {
        assert.equal(activeTheme.navBackground, activeTheme.panelBackground, `${viewport.name}/${screens[index].id}: top navigation background should follow its showcase theme`)
        const panel = page.locator(`#${screens[index].id}.showcase-panel[data-feature="${screens[index].feature}"]`)
        const marker = panel.locator('.feature-demo-note')
        await marker.waitFor({ state: 'visible' })
        assert.match(await marker.innerText(), /项目机制示意/, `${viewport.name}/${screens[index].id}: visible mechanism marker should remain attached to the active showcase`)
        if (screens[index].id === 'feedback-loop') {
          const headline = (await panel.locator('h2').innerText()).replace(/\s+/g, ' ')
          assert.match(headline, /反馈/, `${viewport.name}: feedback screen headline should name feedback`)
          assert.match(headline, /转折/, `${viewport.name}: feedback screen headline should make the route change explicit`)
        }
      }
      evidence.themeChecks.push({ viewport: viewport.name, screen: screens[index].id, expectedTheme, ...activeTheme })
      if (paged) await fullScreenGeometry(page, `${screens[index].id}/${viewport.name}`, index)
      if (viewport.name === 'desktop') await screenshot(page, `screen-${screens[index].id}-desktop.png`)
      if (viewport.name === 'panoramic' && index === 0) await screenshot(page, 'after-home-panoramic.png')
    }
    const capabilityControls = page.locator('#features .feature-card')
    assert.equal(await capabilityControls.count(), 4, `${viewport.name}: capability screen should expose four feature links`)
    assert.equal(await page.locator('#features .capability-art svg').count(), 4, `${viewport.name}: capability screen should include all four diagrams`)
    for (const selector of ['.back-to-overview', '.feature-invitation .primary-action']) {
      assert.equal(await page.locator(`#features ${selector}`).count(), 1, `${viewport.name}: capability screen should expose ${selector}`)
    }
    await page.goto(`${base}/login?auth=1`, { waitUntil: 'networkidle' })
    await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
    await stable(page)
    await geometry(page, `login/${viewport.name}`)
    await reachable(page.locator('.access-submit'))
    if (viewport.name === 'desktop' || viewport.name === 'mobile') await screenshot(page, `after-login-${viewport.name}.png`)
    await page.getByRole('link', { name: '创建账号', exact: true }).click()
    await page.getByRole('dialog', { name: '注册账号', exact: true }).waitFor()
    await geometry(page, `register/${viewport.name}`)
    await reachable(page.locator('.access-submit'))
    if (viewport.name === 'desktop') await screenshot(page, 'after-register-desktop.png')
    await page.locator('summary').click()
    await geometry(page, `register-expanded/${viewport.name}`)
    await reachable(page.locator('.access-submit'))
    await page.close()
  }

  const page = await newPage()
  await page.goto(base, { waitUntil: 'networkidle' })
  await stable(page)
  await page.mouse.move(600, 400)
  await page.mouse.wheel(0, 120)
  await screenSettled(page, 1)
  await page.waitForTimeout(220)
  await page.mouse.wheel(0, 120)
  await screenSettled(page, 2)
  await page.waitForTimeout(220)
  await page.mouse.wheel(0, -120)
  await screenSettled(page, 1)
  await page.waitForTimeout(220)
  await page.mouse.wheel(0, -120)
  await screenSettled(page, 0)
  await page.mouse.wheel(0, 120)
  await page.waitForTimeout(60)
  await page.mouse.wheel(0, -120)
  await screenSettled(page, 0)
  await page.waitForTimeout(220)
  await page.mouse.wheel(0, 120)
  await screenSettled(page, 1)
  await page.waitForTimeout(220)
  await page.getByRole('button', { name: '第 5 屏：成长航线' }).click()
  await screenSettled(page, 4)
  await page.getByRole('button', { name: '第 6 屏：反馈进阶' }).click()
  await screenSettled(page, 5)
  await page.getByRole('button', { name: '第 1 屏：学习概览' }).click()
  await screenSettled(page, 0)
  await page.locator('.landing-main').focus()
  for (const [key, target] of [['PageDown', 1], ['PageDown', 2], ['PageUp', 1], ['PageUp', 0], ['ArrowDown', 1], ['ArrowUp', 0], ['End', 5], ['PageUp', 4], ['Home', 0]]) {
    await page.keyboard.press(key)
    await screenSettled(page, target)
  }
  assert.equal(await page.locator('.landing-nav .nav-feature-link').count(), 0, 'Top navigation should expose only login beside the brand')
  await page.locator('.hero-actions .secondary-action').click()
  await page.waitForURL(`${base}/#features`)
  await screenSettled(page, 1)
  const featurePaths = ['#multi-agent', '#evidence', '#learning-path', '#feedback-loop']
  for (const [index, href] of featurePaths.entries()) {
    const featureCard = page.locator('#features .feature-card').nth(index)
    assert.equal(await featureCard.evaluate(el => el.tagName), 'A', `Feature link ${index + 1} should remain a native anchor`)
    assert.equal(await featureCard.getAttribute('href'), href, `Feature link ${index + 1} should keep its destination`)
    await featureCard.click()
    await page.waitForURL(`${base}/${href}`)
    await screenSettled(page, index + 2)
    if (index === 0) {
      await page.goBack({ waitUntil: 'networkidle' })
      await page.waitForURL(`${base}/#features`)
      await screenSettled(page, 1)
      await page.goForward({ waitUntil: 'networkidle' })
      await page.waitForURL(`${base}/${href}`)
      await screenSettled(page, index + 2)
    }
    await page.goBack({ waitUntil: 'networkidle' })
    await page.waitForURL(`${base}/#features`)
    await screenSettled(page, 1)
  }
  const capabilityCta = page.locator('#features .feature-invitation .primary-action')
  await reachable(capabilityCta)
  await capabilityCta.click()
  await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
  await page.locator('.modal-close').click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  await screenSettled(page, 1)
  await page.locator('#features .back-to-overview').click()
  await page.waitForURL(`${base}/`)
  await screenSettled(page, 0)
  await page.goto(`${base}/#multi-agent`, { waitUntil: 'networkidle' })
  await screenSettled(page, 2)
  await page.setViewportSize({ width: 1440, height: 900 })
  await screenSettled(page, 2)
  await fullScreenGeometry(page, 'multi-agent/resize', 2)
  await page.goto(`${base}/#overview`, { waitUntil: 'networkidle' })
  await screenSettled(page, 0)
  await page.setViewportSize({ width: 1257, height: 860 })
  await screenSettled(page, 0)
  const nativeZoom = await page.locator('.landing-main').evaluate(el => !el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 120, ctrlKey: true })))
  assert.equal(nativeZoom, false, 'System zoom gesture was intercepted')
  evidence.interactions.push('one screen per wheel gesture, repeated relative steps, reversed in-flight gesture, six pagination states, PageUp/PageDown/Home/End, hash refresh/back/forward, four capability links, capability login CTA and return-to-overview, system zoom preserved')
  // Real external-browser CSS viewports where a single oversized chapter used to
  // disable pagination and wheel navigation for all six chapters.
  for (const viewport of [{ width: 1536, height: 844 }, { width: 1707, height: 938 }, { width: 1920, height: 1056 }]) {
    const desktop = await newPage({ viewport, deviceScaleFactor: 1 })
    await desktop.goto(base, { waitUntil: 'networkidle' })
    await stable(desktop)
    await desktop.locator('.screen-pagination').waitFor({ state: 'visible' })
    const navigationStyle = await desktop.locator('.screen-pagination').evaluate(el => {
      const style = getComputedStyle(el)
      return { background: style.backgroundColor, border: style.borderTopWidth, blur: style.backdropFilter }
    })
    assert.equal(navigationStyle.background, 'rgba(0, 0, 0, 0)', 'Vertical markers must have no surrounding bubble background')
    assert.equal(navigationStyle.border, '0px', 'Vertical markers must have no surrounding border')
    assert.equal(navigationStyle.blur, 'none', 'Vertical markers must have no surrounding backdrop effect')
    assert.equal(await desktop.locator('.screen-pagination').innerText(), '', 'Pagination must show only vertical markers')
    assert.equal(await desktop.locator('.screen-pagination i').count(), 6)
    await geometry(desktop, `external-browser/${viewport.width}x${viewport.height}`)
    await desktop.evaluate(() => {
      const main = document.querySelector('.landing-main')
      window.__screenMotion = []
      const start = performance.now()
      function sample(now) {
        window.__screenMotion.push({ time: now - start, top: main.scrollTop })
        if (now - start < 1300) requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
    })
    await desktop.mouse.move(300, 350)
    await desktop.mouse.wheel(0, 120)
    await desktop.waitForTimeout(280)
    // A second same-direction packet after the former 180ms lock must not skip a chapter.
    await desktop.mouse.wheel(0, 120)
    await screenSettled(desktop, 1)
    await desktop.waitForTimeout(600)
    const motion = await desktop.evaluate(() => ({ samples: window.__screenMotion, target: document.querySelector('#features').offsetTop }))
    const moving = motion.samples.filter(sample => sample.top > 2 && sample.top < motion.target - 2)
    assert.ok(new Set(moving.map(sample => sample.top)).size >= 10, 'Transition must contain multiple distinct intermediate frames')
    assert.ok(moving.at(-1).time - moving[0].time >= 450, 'Transition must not collapse to a native immediate jump')
    assert.ok(motion.samples.every((sample, index) => index === 0 || sample.top >= motion.samples[index - 1].top - 1), 'Same-direction input must not restart or reverse the transition')
    assert.ok(Math.abs(motion.samples.at(-1).top - motion.target) < 2, 'Motion must finish at the destination')
    const bounds = await desktop.evaluate(() => {
      const screen = document.querySelector('#features')
      const main = document.querySelector('.landing-main')
      return { start: screen.offsetTop, end: screen.offsetTop + screen.offsetHeight - main.clientHeight, height: screen.offsetHeight, viewport: main.clientHeight }
    })
    if (bounds.end > bounds.start + 2) {
      await desktop.mouse.wheel(0, 120)
      await desktop.waitForFunction(end => Math.abs(document.querySelector('.landing-main').scrollTop - end) < 2, bounds.end)
      assert.equal(await desktop.locator('.screen-pagination button[aria-current]').getAttribute('aria-controls'), 'features', 'Reading the oversized chapter must not activate the next chapter early')
      await desktop.waitForTimeout(250)
    }
    await desktop.mouse.wheel(0, 120)
    await screenSettled(desktop, 2)
    assert.equal(await desktop.locator('.screen-pagination button[aria-current]').getAttribute('aria-controls'), 'multi-agent')
    await desktop.waitForTimeout(250)
    await desktop.mouse.wheel(0, -120)
    await desktop.waitForFunction(end => Math.abs(document.querySelector('.landing-main').scrollTop - end) < 2, bounds.end)
    assert.equal(await desktop.locator('.screen-pagination button[aria-current]').getAttribute('aria-controls'), 'features', 'Upward entry must land at the oversized chapter bottom')
    await desktop.getByRole('button', { name: '第 1 屏：学习概览' }).click()
    await screenSettled(desktop, 0)
    await screenshot(desktop, `external-browser-${viewport.width}x${viewport.height}.png`)
    evidence.desktopScrollChecks.push({ viewport, bounds, motion })
    await desktop.close()
  }
  const cancellation = await newPage({ viewport: { width: 1536, height: 844 }, deviceScaleFactor: 1 })
  await cancellation.goto(base, { waitUntil: 'networkidle' })
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(250)
  await cancellation.setViewportSize({ width: 1707, height: 938 })
  await screenSettled(cancellation, 1)
  await cancellation.waitForTimeout(850)
  await screenSettled(cancellation, 1)
  await cancellation.getByRole('button', { name: '第 1 屏：学习概览' }).click()
  await screenSettled(cancellation, 0)
  await cancellation.waitForTimeout(250)
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(250)
  await cancellation.emulateMedia({ reducedMotion: 'reduce' })
  await screenSettled(cancellation, 1)
  await cancellation.waitForTimeout(850)
  await screenSettled(cancellation, 1)
  assert.equal(await cancellation.locator('.landing-main').evaluate(el => el.style.scrollSnapType), '', 'Completed or cancelled RAF must restore the scroll policy')
  await cancellation.emulateMedia({ reducedMotion: 'no-preference' })
  await cancellation.getByRole('button', { name: '第 1 屏：学习概览' }).click()
  await screenSettled(cancellation, 0)
  await cancellation.waitForTimeout(250)
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(250)
  await cancellation.locator('.login-trigger').click()
  await cancellation.getByRole('dialog').waitFor()
  const modalTop = await cancellation.locator('.landing-main').evaluate(el => el.scrollTop)
  await cancellation.waitForTimeout(850)
  assert.equal(await cancellation.locator('.landing-main').evaluate(el => el.scrollTop), modalTop, 'Opening a modal must cancel background RAF')
  await cancellation.locator('.modal-close').click()
  await cancellation.getByRole('dialog').waitFor({ state: 'hidden' })
  await cancellation.goto(`${base}/#features`, { waitUntil: 'networkidle' })
  await screenSettled(cancellation, 1)
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(80)
  await cancellation.mouse.wheel(0, -40)
  await cancellation.waitForTimeout(450)
  await screenSettled(cancellation, 1)
  assert.equal(await cancellation.locator('.screen-pagination button[aria-current]').getAttribute('aria-controls'), 'features', 'Reversing a boundary adjustment must keep reading the current chapter')
  const contentEnd = await cancellation.evaluate(() => {
    const main = document.querySelector('.landing-main'), screen = document.querySelector('#features')
    return screen.offsetTop + screen.offsetHeight - main.clientHeight
  })
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(80)
  await cancellation.emulateMedia({ reducedMotion: 'reduce' })
  await cancellation.waitForFunction(end => Math.abs(document.querySelector('.landing-main').scrollTop - end) < 2, contentEnd)
  await cancellation.waitForTimeout(450)
  assert.ok(Math.abs(await cancellation.locator('.landing-main').evaluate(el => el.scrollTop) - contentEnd) < 2, 'Reduced motion must finish and stop the boundary movement')
  await cancellation.emulateMedia({ reducedMotion: 'no-preference' })
  await cancellation.goto(`${base}/#feedback-loop`, { waitUntil: 'networkidle' })
  await screenSettled(cancellation, 5)
  await cancellation.locator('#feedback-loop .feature-world').evaluate(el => el.style.paddingBottom = '500px')
  await cancellation.waitForTimeout(100)
  const lastBottom = await cancellation.locator('.landing-main').evaluate(el => {
    const top = el.scrollHeight - el.clientHeight
    el.scrollTo({ top, behavior: 'instant' })
    return top
  })
  await cancellation.waitForTimeout(250)
  await cancellation.mouse.move(300, 350)
  await cancellation.mouse.wheel(0, 120)
  await cancellation.waitForTimeout(900)
  assert.ok(Math.abs(await cancellation.locator('.landing-main').evaluate(el => el.scrollTop) - lastBottom) < 2, 'Downward wheel at the final chapter bottom must preserve its reading position')
  await cancellation.close()
  evidence.interactions.push('external desktop pagination remains visible, 760ms complete monotonic motion, repeated wheel lock, oversized content boundary, resize/reduced-motion/modal cancellation')
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.keyboard.press('Tab')
  assert.equal(await page.locator('.skip-link').evaluate(el => el === document.activeElement), true)
  await contrast(page, '.primary-action')
  await contrast(page, '.hero-content > p')
  await page.locator('#overview').getByRole('button', { name: '开始我的学习', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '账号登录', exact: true })
  await dialog.waitFor()
  await stable(page)
  const backgroundScroll = await page.locator('.landing-main').evaluate(el => el.scrollTop)
  await page.mouse.move(20, 400)
  await page.mouse.wheel(0, 120)
  await page.keyboard.press('PageDown')
  assert.equal(await page.locator('.landing-main').evaluate(el => el.scrollTop), backgroundScroll, 'Modal input moved the background screen')
  const access1257 = await accessGeometry(page, 'account/1257x860')
  const expectedDesktopHeight = Math.min(760, access1257.viewport.height - 64)
  assert.ok(Math.abs(access1257.dialog.height - expectedDesktopHeight) < 2, `1257x860: dialog height should be min(760px, viewport - 64px), got ${access1257.dialog.height}`)
  assert.ok(Math.abs(access1257.body.height - access1257.dialogContentHeight) < 2, 'Dialog body should fill the dialog content box')
  assert.ok(Math.abs(access1257.layout.height - access1257.body.height) < 2, 'Dialog layout should fill the body height')
  await inputSurfaceCheck(page, 'login/username')
  const storyContrast = await contrastOnSurface(page, '.access-story-title', '.access-story', '左侧登录视觉标题')
  const formTitleContrast = await contrastOnSurface(page, '.access-form-panel h2', '.access-form-side', '登录标题')
  await contrastOnSurface(page, '.access-form-subtitle', '.access-form-side', '登录说明')
  await contrastOnSurface(page, '.access-form .el-form-item__label', '.access-form-side', '登录字段标签')
  await contrastOnSurface(page, '#signin-username', '.el-input__wrapper', '用户名占位文字', '::placeholder')
  const submitContrast = await contrastOnSurface(page, '.access-submit', '.access-submit', '登录主按钮')
  assert.ok(storyContrast.minimumBackgroundLuminance > .65, `Login story background should stay light: ${storyContrast.minimumBackgroundLuminance}`)
  assert.ok(formTitleContrast.minimumBackgroundLuminance > .8, `Login form background should stay light: ${formTitleContrast.minimumBackgroundLuminance}`)
  evidence.accessScrollChecks.push({ label: 'account/light surfaces', stage: 'contrast surfaces', storyBackgroundMinimumLuminance: storyContrast.minimumBackgroundLuminance, formBackgroundMinimumLuminance: formTitleContrast.minimumBackgroundLuminance, submitWorstEndpoint: submitContrast.worstBackground })
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press(i % 2 ? 'Shift+Tab' : 'Tab')
    assert.equal(await dialog.evaluate(el => el.contains(document.activeElement)), true, 'Focus escaped the modal')
  }
  await page.locator('.modal-close').focus()
  const focus = await page.locator('.modal-close').evaluate(el => ({ style: getComputedStyle(el).outlineStyle, width: getComputedStyle(el).outlineWidth }))
  assert.notEqual(focus.style, 'none')
  assert.ok(parseFloat(focus.width) >= 2)
  await contrast(page, '.access-submit')
  await contrast(page, '.access-form-subtitle')
  await page.getByLabel('用户名', { exact: true }).fill('ui_fixture')
  await contrastOnSurface(page, '#signin-username', '.el-input__wrapper', '实际用户名文字')
  const portalFirst = await portalMotion(page, 'first login opening')
  await page.waitForTimeout(850)
  const portalSecond = await portalMotion(page, 'first login opening after 850ms')
  assert.notEqual(portalSecond.core.transform, portalFirst.core.transform, 'Portal core transform should change during automatic playback')
  assert.notEqual(portalSecond.tracer.offsetDistance, portalFirst.tracer.offsetDistance, 'Tracer offset-distance should change during automatic playback')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  const pausedPortal = await page.evaluate(() => {
    const svg = document.querySelector('.portal-art')
    if (!svg) return null
    const targets = [svg.querySelector('.portal-core'), svg.querySelector('.portal-tracer')].filter(Boolean)
    return {
      active: svg.classList.contains('is-active'),
      states: [...document.getAnimations({ subtree: true })]
        .filter(animation => targets.includes(animation.effect?.target))
        .map(animation => animation.playState),
    }
  })
  assert.ok(!pausedPortal || pausedPortal.states.length === 0 || pausedPortal.states.every(state => state === 'paused'), 'Closing the auth dialog should pause its CSS illustration loops')
  await page.waitForFunction(() => document.activeElement?.classList.contains('primary-action'))
  assert.equal(new URL(page.url()).searchParams.has('auth'), false)
  await page.locator('.login-trigger').click()
  await dialog.waitFor()
  const reopenedFirst = await portalMotion(page, 'reopened login')
  await page.waitForTimeout(700)
  const reopenedSecond = await portalMotion(page, 'reopened login after 700ms')
  assert.notEqual(reopenedSecond.core.transform, reopenedFirst.core.transform, 'Reopened portal core animation should continue or restart')
  assert.notEqual(reopenedSecond.tracer.offsetDistance, reopenedFirst.tracer.offsetDistance, 'Reopened tracer animation should continue or restart')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  await page.waitForFunction(() => document.activeElement?.classList.contains('login-trigger'))
  evidence.portalAnimationChecks.push({ initial: { coreTransform: portalFirst.core.transform, tracerOffsetDistance: portalFirst.tracer.offsetDistance }, later: { coreTransform: portalSecond.core.transform, tracerOffsetDistance: portalSecond.tracer.offsetDistance }, reopened: { coreTransform: reopenedSecond.core.transform, tracerOffsetDistance: reopenedSecond.tracer.offsetDistance }, closedStates: pausedPortal?.states ?? [], result: 'automatic loop, close pause, reopen playback; open double orbits; no pause control' })
  evidence.interactions.push('skip link, visible focus, modal Tab/Shift+Tab containment, Escape, opener focus restored')

  await page.goto(`${base}/login?auth=1&redirect=%2Fdashboard%3Fsource%3Dentry`, { waitUntil: 'networkidle' })
  await page.locator('.access-submit').click()
  assert.equal(await page.getByLabel('用户名', { exact: true }).evaluate(el => el === document.activeElement), true)
  assert.equal(state.logins.length, 0)
  await page.getByLabel('用户名', { exact: true }).fill('ui_fixture')
  await page.locator('.access-submit').click()
  assert.equal(await page.getByLabel('密码', { exact: true }).evaluate(el => el === document.activeElement), true)
  await page.getByLabel('密码', { exact: true }).fill(fixturePassword)
  await page.getByRole('button', { name: '显示密码', exact: true }).click()
  assert.equal(await page.getByLabel('密码', { exact: true }).getAttribute('type'), 'text')
  await page.getByRole('button', { name: '隐藏密码', exact: true }).click()
  assert.equal(await page.getByLabel('密码', { exact: true }).getAttribute('type'), 'password')
  await page.getByLabel('密码', { exact: true }).press('Enter')
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByRole('alert').innerText(), '用户名或密码错误')
  await contrastOnSurface(page, '.access-error', '.access-error', '登录服务错误文字')
  assert.equal(state.logins.length, 1)
  assert.deepEqual(state.logins[0], { username: 'ui_fixture', password: fixturePassword })
  assert.equal(await page.getByLabel('密码', { exact: true }).inputValue(), fixturePassword)
  await screenshot(page, 'login-error-desktop.png')
  state.loginOutcome = 'success'
  await page.getByLabel('密码', { exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.waitForURL(`${base}/dashboard?source=entry`)
  assert.equal(state.logins.length, 2, 'One Enter action should issue only one login request')
  evidence.interactions.push('required-field focus, password toggle, login rejection, retained inputs, one request per submit, safe redirect')

  state.user = null
  await page.goto(`${base}/login?auth=1&redirect=%2F%2Fexample.invalid`, { waitUntil: 'networkidle' })
  await page.getByLabel('用户名', { exact: true }).fill('ui_fixture')
  await page.getByLabel('密码', { exact: true }).fill(fixturePassword)
  await page.locator('.access-submit').click()
  await page.waitForURL(`${base}/dashboard`)
  state.user = null
  await page.goto(`${base}/register?auth=1`, { waitUntil: 'networkidle' })
  await page.getByLabel('用户名', { exact: true }).fill('ui_fixture')
  await page.getByLabel('密码', { exact: true }).fill('short')
  await page.locator('.access-submit').click()
  await page.getByText('密码至少需要 8 位', { exact: true }).waitFor()
  await contrastOnSurface(page, '.el-form-item__error', '.access-form-side', '注册字段校验错误')
  await page.getByLabel('密码', { exact: true }).fill(fixturePassword)
  await page.getByLabel('确认密码', { exact: true }).fill('different')
  await page.locator('.access-submit').click()
  await page.getByText('请确认两次输入的密码一致', { exact: true }).waitFor()
  assert.equal(state.registrations.length, 0)
  await page.getByLabel('确认密码', { exact: true }).fill(fixturePassword)
  await page.locator('.access-submit').click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByRole('alert').innerText(), '该用户名已存在')
  await contrastOnSurface(page, '.access-error', '.access-error', '注册服务错误文字')
  assert.deepEqual(state.registrations[0], { username: 'ui_fixture', password: fixturePassword, confirm_password: fixturePassword, identity: null, education: null, major: null, job_role: null, experience_years: null })
  await profileScrollCheck(page, 'desktop-1257x860')
  await page.getByLabel('身份', { exact: true }).fill('验收学生')
  await page.getByLabel('学历', { exact: true }).fill('本科')
  await page.getByLabel('专业', { exact: true }).fill('软件工程')
  await page.getByLabel('岗位 / 背景', { exact: true }).fill('界面验收')
  await page.getByRole('spinbutton', { name: '经验年限' }).fill('2')
  state.registerOutcome = 'success'
  await page.locator('.access-submit').click()
  await page.waitForURL(`${base}/dashboard`)
  assert.deepEqual(state.registrations[1], { username: 'ui_fixture', password: fixturePassword, confirm_password: fixturePassword, identity: '验收学生', education: '本科', major: '软件工程', job_role: '界面验收', experience_years: 2 })
  evidence.interactions.push('unsafe redirect rejected, registration validation/rejection/success, unchanged optional-field payload')

  const profilePage = await newPage({ viewport: { width: 1331, height: 860 }, deviceScaleFactor: 1 })
  for (const viewport of [
    { label: 'desktop-1331x860', width: 1331, height: 860 },
    { label: 'mobile-390x844', width: 390, height: 844 },
    { label: 'mobile-lowheight-390x520', width: 390, height: 520 },
  ]) {
    state.user = null
    await profilePage.setViewportSize({ width: viewport.width, height: viewport.height })
    await profilePage.goto(`${base}/register?auth=1`, { waitUntil: 'networkidle' })
    await profilePage.getByRole('dialog', { name: '注册账号', exact: true }).waitFor()
    await stable(profilePage)
    await profileScrollCheck(profilePage, viewport.label)
  }
  await profilePage.close()

  state.user = null
  await page.goto(`${base}/?login=1&redirect=%2Fdashboard`, { waitUntil: 'networkidle' })
  await page.getByRole('dialog', { name: '账号登录', exact: true }).waitFor()
  await page.locator('.modal-close').click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  assert.equal(new URL(page.url()).searchParams.get('redirect'), '/dashboard')
  await page.goto(`${base}/login?auth=1`, { waitUntil: 'networkidle' })
  await page.locator('.modal-close').click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  assert.equal(new URL(page.url()).pathname, '/')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.locator('.login-trigger').click()
  await page.getByRole('dialog').waitFor()
  assert.equal(await page.locator('.modal-close').evaluate(el => getComputedStyle(el).transitionDuration), '0s')
  assert.equal(await page.locator('.landing-page').evaluate(el => getComputedStyle(el).scrollBehavior), 'auto')
  const reducedPortal = await page.evaluate(() => {
    const svg = document.querySelector('.portal-art')
    const targets = [svg?.querySelector('.portal-core'), svg?.querySelector('.portal-tracer')].filter(Boolean)
    const active = [...document.getAnimations({ subtree: true })]
      .filter(animation => targets.includes(animation.effect?.target) && ['running', 'pending'].includes(animation.playState))
    return {
      activeAnimations: active.length,
      coreName: svg?.querySelector('.portal-core') ? getComputedStyle(svg.querySelector('.portal-core')).animationName : 'missing',
      tracerName: svg?.querySelector('.portal-tracer') ? getComputedStyle(svg.querySelector('.portal-tracer')).animationName : 'missing',
      pauseControls: svg?.querySelectorAll('button, [role="button"]').length ?? 0,
    }
  })
  assert.equal(reducedPortal.activeAnimations, 0, 'Reduced motion must leave no running portal loop')
  assert.equal(reducedPortal.pauseControls, 0, 'Reduced motion must not add a manual pause control')
  evidence.portalAnimationChecks.push({ reducedMotion: reducedPortal })
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '第 2 屏：平台能力' }).click()
  await screenSettled(page, 1)
  assert.equal(await page.locator('.landing-main').evaluate(el => getComputedStyle(el).scrollBehavior), 'auto')
  evidence.interactions.push('query login, direct login close routes home, retained redirect, reduced motion')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.setViewportSize({ width: 1257, height: 520 })
  assert.equal(await page.locator('.landing-page').evaluate(el => el.classList.contains('is-paged')), false)
  const nativeWheel = await page.locator('.landing-main').evaluate(el => !el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -120 })))
  assert.equal(nativeWheel, false, 'Low-height viewport wheel was intercepted')
  await page.mouse.move(600, 300)
  await page.mouse.wheel(0, -120)
  await reachable(page.locator('#features .screen-cue'))
  await page.setViewportSize({ width: 1257, height: 860 })
  await page.locator('.hero-content').evaluate(el => el.style.paddingBlock = '600px')
  await page.waitForFunction(() => !document.querySelector('.landing-page').classList.contains('is-paged'))
  await page.getByRole('button', { name: '第 1 屏：学习概览' }).click()
  await screenSettled(page, 0)
  const oversizedWheel = await page.locator('.landing-main').evaluate(el => !el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 120 })))
  assert.equal(oversizedWheel, false, 'Oversized content wheel was intercepted')
  evidence.interactions.push('low-height and oversized content retain natural scrolling')
  await page.close()
  assert.deepEqual(errors, [], 'Browser page errors')
  evidence.status = 'PASS'
  console.log(`Landing browser PASS: ${evidence.viewportChecks.length} layout checks, ${evidence.screenChecks.length} full-screen checks, ${evidence.contrastChecks.length} contrast checks, ${evidence.accessScrollChecks.length} access checks, ${evidence.portalAnimationChecks.length} animation checks; ${reportDir}`)
} catch (error) {
  evidence.status = 'FAIL'
  evidence.failure = error.stack
  throw error
} finally {
  writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify(evidence, null, 2))
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
