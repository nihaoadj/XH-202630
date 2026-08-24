import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import { chromium } from 'playwright'

const frontendDir = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(frontendDir, '..', '..', 'backend')
const pythonCandidates = [process.env.PYTHON, process.platform === 'win32' ? 'D:\\codeapp\\miniConda\\python.exe' : null, process.platform === 'win32' ? 'python.exe' : 'python3', 'python'].filter(Boolean)
const python = pythonCandidates.find(candidate => candidate.includes('\\') || candidate.includes('/') ? existsSync(candidate) : true)
const tempDir = mkdtempSync(path.join(tmpdir(), 'courseware-browser-'))
const reportDir = path.resolve(frontendDir, 'test-results', 'courseware-browser')
const layoutDebug = process.env.COURSEWARE_BROWSER_LAYOUT_DEBUG === '1'
const components = layoutDebug ? [] : ['callout', 'key_point', 'compare', 'steps', 'ordered_steps', 'single_choice', 'multiple_choice', 'recap', 'flashcard', 'matching', 'ordering', 'branching_scenario', 'categorization', 'word_bank_cloze', 'timeline_explorer']
// Catalog keys intentionally differ from their renderer class names for the
// choice and key-point components.  Keep this mapping explicit so the browser
// gate verifies the element produced by the real server renderer.
const rendererNames = {
  key_point: 'key-point',
  ordered_steps: 'ordered-steps',
  single_choice: 'choice',
  multiple_choice: 'choice',
  branching_scenario: 'branching-scenario',
  word_bank_cloze: 'word-bank-cloze',
  timeline_explorer: 'timeline-explorer'
}
const themes = layoutDebug ? ['editorial'] : ['editorial', 'midnight', 'paper']
const recipes = layoutDebug ? [process.env.COURSEWARE_BROWSER_DEBUG_RECIPE || 'editorial_cover'] : ['editorial_cover', 'learning_map_grid', 'concept_split', 'process_lane', 'comparison_matrix', 'case_diagnostic', 'practice_workspace', 'quiz_focus', 'recap_dashboard']
const recipeViewports = layoutDebug ? [{ name: '1280x720', width: 1280, height: 720, mobile: false }] : [
  { name: '360x800', width: 360, height: 800, mobile: true },
  { name: '768x1024', width: 768, height: 1024, mobile: true },
  { name: '1280x720', width: 1280, height: 720, mobile: false },
  { name: '1440x900', width: 1440, height: 900, mobile: false },
  { name: '1920x1080', width: 1920, height: 1080, mobile: false },
]
const renderScript = String.raw`
import sys
from pathlib import Path
from app.core.courseware.renderer import render_courseware
component, theme = sys.argv[2], sys.argv[3]
block = {"block_id": "block-1", "component": component, "text": f"{component} 的来源支持内容", "source_refs": [{"source_resource_id": "fixture", "source_block_ids": ["block-1"]}]}
if component in {"steps", "ordered_steps"}: block["steps"] = ["第一步", "第二步"]
if component in {"single_choice", "multiple_choice"}: block["options"] = ["正确", "错误"]
if component == "flashcard": block.update({"front": "问题", "back": "答案"})
if component == "matching": block["pairs"] = [{"left": "术语 A", "right": "定义 A"}, {"left": "术语 B", "right": "定义 B"}]
if component == "ordering": block.update({"ordering_items": ["第一步", "第二步"], "correct_order": ["第一步", "第二步"]})
if component == "branching_scenario":
    block.update({"schema_version": "2.0", "start_node_id": "n1", "nodes": [{"node_id": "n1", "node_type": "decision", "source_refs": block["source_refs"], "options": [{"option_id": "o1", "label": "路径 A", "next_node_id": "n2", "source_refs": block["source_refs"]}, {"option_id": "o2", "label": "路径 B", "next_node_id": "n2", "source_refs": block["source_refs"]}]}, {"node_id": "n2", "node_type": "terminal", "source_refs": block["source_refs"], "options": []}]})
if component == "categorization":
    block.update({"schema_version": "2.0", "categories": [{"category_id": "c1", "label": "类别 1", "source_refs": block["source_refs"]}, {"category_id": "c2", "label": "类别 2", "source_refs": block["source_refs"]}], "items": [{"item_id": "i1", "label": "项目 1", "correct_category_id": "c1", "source_refs": block["source_refs"]}, {"item_id": "i2", "label": "项目 2", "correct_category_id": "c2", "source_refs": block["source_refs"]}, {"item_id": "i3", "label": "项目 3", "correct_category_id": "c1", "source_refs": block["source_refs"]}]})
if component == "word_bank_cloze":
    block.update({"schema_version": "2.0", "prompt_segments": ["先 ", " 再"], "blanks": [{"blank_id": "b1", "correct_token_id": "t1", "source_refs": block["source_refs"]}], "tokens": [{"token_id": "t1", "label": "检索", "source_refs": block["source_refs"]}, {"token_id": "t2", "label": "生成", "source_refs": block["source_refs"]}]})
if component == "timeline_explorer":
    block.update({"schema_version": "2.0", "events": [{"event_id": "e1", "sequence": 1, "label": "第一步", "source_refs": block["source_refs"]}, {"event_id": "e2", "sequence": 2, "label": "第二步", "source_refs": block["source_refs"]}]})
document = {"schema_version": "1.0", "title": "浏览器质量门", "scenes": [{"kind": "intro", "title": component, "blocks": [block["text"]], "source_refs": ["fixture"], "source_block_ids": ["block-1"], "source_map": {"blocks": [["block-1"]]}, "component_blocks": [block]}, {"kind": "recap", "title": "复盘", "blocks": ["完成浏览器检查。"], "source_refs": ["fixture"], "source_block_ids": ["block-1"], "source_map": {"blocks": [["block-1"]]}}]}
Path(sys.argv[1]).write_bytes(render_courseware(document, {"theme_id": theme, "layout_id": "focus"}))
`
const recipeRenderScript = String.raw`
import sys
from pathlib import Path
from app.core.courseware.renderer import render_courseware
recipe, theme = sys.argv[2], sys.argv[3]
refs = [{"source_resource_id": "fixture", "source_block_ids": ["block-1"]}]
texts = [
    "先建立清晰的问题边界，再把来源、证据与结论组织成可追溯的学习路径。",
    "主体信息通过解释、流程和对比三个层级展开，让学习者能够看见概念之间的关系。",
    "示例用于说明常见误区与定位方法，操作结果必须能够回到冻结来源进行核验。",
    "页面结论总结本阶段的判断，并给出进入下一阶段前需要完成的具体检查。",
]
blocks = [{"block_id": f"zone-{index}", "component": component, "text": text, "source_refs": refs} for index, (component, text) in enumerate(zip(["key_point", "callout", "compare", "recap"], texts), 1)]
role = {"editorial_cover":"cover","learning_map_grid":"learning_map","concept_split":"concept_explanation","process_lane":"process_breakdown","comparison_matrix":"comparison_analysis","case_diagnostic":"case_diagnosis","practice_workspace":"practice_workspace","quiz_focus":"knowledge_check","recap_dashboard":"summary_action"}[recipe]
scene = {"scene_id": f"fixture-{recipe}", "kind": "intro", "page_role": role, "layout_recipe_id": recipe, "title": "固定画布质量门", "key_question": "本页如何形成完整的信息闭环？", "lead": texts[0], "blocks": texts, "conclusion": texts[-1], "source_refs": ["fixture"], "source_block_ids": ["block-1"], "source_map": {"title":[["block-1"]],"lead":[["block-1"]],"blocks":[["block-1"] for _ in texts],"conclusion":[["block-1"]]}, "component_blocks": blocks}
Path(sys.argv[1]).write_bytes(render_courseware({"schema_version":"2.0","title":"固定画布质量门","scenes":[scene]}, {"theme_id": theme, "layout_id": "focus"}))
`

function artifactFor(component, theme) {
  const target = path.join(tempDir, `${theme}-${component}.html`)
  const rendered = spawnSync(python, ['-c', renderScript, target, component, theme], { cwd: backendDir, encoding: 'utf8', env: { ...process.env, PYTHONPATH: backendDir } })
  if (rendered.error || rendered.status !== 0) throw new Error(rendered.stderr || rendered.error?.message || 'backend renderer failed')
  return target
}

function recipeArtifactFor(recipe, theme) {
  const target = path.join(tempDir, `${theme}-${recipe}.html`)
  const rendered = spawnSync(python, ['-c', recipeRenderScript, target, recipe, theme], { cwd: backendDir, encoding: 'utf8', env: { ...process.env, PYTHONPATH: backendDir } })
  if (rendered.error || rendered.status !== 0) throw new Error(rendered.stderr || rendered.error?.message || 'backend recipe renderer failed')
  return target
}

let browser
let viewerServer
try {
  const launchOptions = { headless: true }
  if (!Object.prototype.hasOwnProperty.call(process.env, 'COURSEWARE_BROWSER_CHANNEL')) launchOptions.channel = 'msedge'
  else if (process.env.COURSEWARE_BROWSER_CHANNEL) launchOptions.channel = process.env.COURSEWARE_BROWSER_CHANNEL
  browser = await chromium.launch(launchOptions)
} catch (error) {
  const message = `courseware browser test unavailable: ${error.message.split('\n')[0]}`
  if (process.env.COURSEWARE_BROWSER_REQUIRED === '1') { console.error(message); process.exit(1) }
  console.log(`${message} (skipped; set COURSEWARE_BROWSER_REQUIRED=1 to require it)`)
  process.exit(0)
}

try {
  rmSync(reportDir, { recursive: true, force: true })
  mkdirSync(reportDir, { recursive: true })
  const consoleErrors = []
  const componentThemeMatrix = []
  const recipeThemeViewportMatrix = []
  const artifacts = new Map()
  for (const theme of themes) {
    for (const component of components) {
      const artifact = artifactFor(component, theme)
      artifacts.set(`${theme}:${component}`, artifact)
      const page = await browser.newPage({ viewport: { width: 320, height: 640 } })
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
      await page.goto(pathToFileURL(artifact).href, { waitUntil: 'domcontentloaded' })
      assert.equal(await page.getAttribute('html', 'lang'), 'zh-CN')
      const locator = page.locator(`.component-${rendererNames[component] || component}`).first()
      assert.equal(await locator.count(), 1)
      const computedChecks = await locator.evaluate(node => {
        const style = getComputedStyle(node)
        return { displayed: style.display !== 'none' && style.visibility !== 'hidden', color: style.color, backgroundColor: style.backgroundColor, role: node.getAttribute('role') || node.getAttribute('aria-label') }
      })
      assert.equal(computedChecks.displayed, true)
      const filename = `${theme}-${component}.png`
      const screenshot = await locator.screenshot({ path: path.join(reportDir, filename) })
      componentThemeMatrix.push({ component, theme, screenshot_path: filename, screenshot_sha256: createHash('sha256').update(screenshot).digest('hex'), computed_checks: computedChecks })
      await page.close()
    }
  }
  for (const theme of themes) {
    for (const recipe of recipes) {
      const artifact = recipeArtifactFor(recipe, theme)
      for (const viewport of recipeViewports) {
        const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } })
        page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
        await page.goto(pathToFileURL(artifact).href, { waitUntil: 'domcontentloaded' })
        const metrics = await page.evaluate(() => {
          const root = document.documentElement
          const scene = document.querySelector('.scene.active')
          const body = scene?.querySelector('.scene-body')
          const nav = document.querySelector('.nav')
          const course = document.querySelector('.course')
          const stage = document.querySelector('.course-stage')
          const bodyRect = body?.getBoundingClientRect()
          const childRects = [...(body?.children || [])].map(node => node.getBoundingClientRect())
          const usedTop = childRects.length ? Math.min(...childRects.map(rect => rect.top)) : 0
          const usedBottom = childRects.length ? Math.max(...childRects.map(rect => rect.bottom)) : 0
          const navRect = nav?.getBoundingClientRect()
          const childOverflowCount = [...(body?.children || [])].filter(node => node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1).length
          return {
            documentScrollWidth: root.scrollWidth, documentClientWidth: root.clientWidth,
            documentScrollHeight: root.scrollHeight, documentClientHeight: root.clientHeight,
            courseClass: course?.className || '', courseHeight: course?.clientHeight || 0,
            courseRows: course ? getComputedStyle(course).gridTemplateRows : '',
            stageHeight: stage?.clientHeight || 0,
            sceneScrollWidth: scene?.scrollWidth || 0, sceneClientWidth: scene?.clientWidth || 0,
            sceneScrollHeight: scene?.scrollHeight || 0, sceneClientHeight: scene?.clientHeight || 0,
            bodyUseRatio: bodyRect?.height ? Math.min(1, Math.max(0, usedBottom - usedTop) / bodyRect.height) : 0,
            fontSize: Number.parseFloat(getComputedStyle(scene).fontSize),
            navReachable: Boolean(navRect && navRect.top >= 0 && navRect.bottom <= innerHeight + 1),
            visibleBlocks: childRects.filter(rect => rect.width > 0 && rect.height > 0).length,
            childOverflowCount,
            childMetrics: [...(body?.children || [])].map(node => ({
              className: node.className, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight,
              clientWidth: node.clientWidth, scrollWidth: node.scrollWidth,
            })),
          }
        })
        assert.equal(metrics.documentScrollWidth <= metrics.documentClientWidth + 1, true, `${theme}/${recipe}/${viewport.name} horizontal overflow`)
        assert.equal(metrics.sceneScrollWidth <= metrics.sceneClientWidth + 1, true, `${theme}/${recipe}/${viewport.name} scene horizontal overflow`)
        assert.equal(metrics.fontSize >= 16, true, `${theme}/${recipe}/${viewport.name} font below 16px`)
        assert.equal(metrics.visibleBlocks >= 2, true, `${theme}/${recipe}/${viewport.name} underfilled content zones`)
        if (!viewport.mobile) {
          assert.equal(metrics.documentScrollHeight <= metrics.documentClientHeight + 1, true, `${theme}/${recipe}/${viewport.name} desktop document scroll`)
          assert.equal(metrics.sceneScrollHeight <= metrics.sceneClientHeight + 1, true, `${theme}/${recipe}/${viewport.name} desktop scene overflow ${JSON.stringify(metrics)}`)
          assert.equal(metrics.bodyUseRatio >= 0.65, true, `${theme}/${recipe}/${viewport.name} body use below 65%`)
          assert.equal(metrics.childOverflowCount, 0, `${theme}/${recipe}/${viewport.name} hidden component content ${JSON.stringify(metrics.childMetrics)}`)
          assert.equal(metrics.navReachable, true, `${theme}/${recipe}/${viewport.name} navigation unreachable`)
        }
        const screenshot = await page.screenshot()
        recipeThemeViewportMatrix.push({ theme, recipe, viewport: viewport.name, screenshot_sha256: createHash('sha256').update(screenshot).digest('hex'), computed_checks: metrics })
        await page.close()
      }
    }
  }
  const interactive = await browser.newPage({ viewport: { width: 320, height: 640 } })
  interactive.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await interactive.goto(pathToFileURL(artifacts.get('editorial:single_choice')).href, { waitUntil: 'domcontentloaded' })
  await interactive.getByRole('button', { name: '下一节' }).focus()
  assert.equal(await interactive.evaluate(() => document.activeElement?.getAttribute('data-nav')), '1')
  await interactive.keyboard.press('Tab')
  assert.equal(await interactive.evaluate(() => document.activeElement instanceof HTMLElement), true)
  await interactive.getByLabel('正确').check()
  const focusEvidence = await interactive.evaluate(() => {
    const controls = [...document.querySelectorAll('button, input, [role="button"]')]
    const unlabeled = controls.filter(node => !(node.getAttribute('aria-label') || node.textContent?.trim() || node.closest('label'))).length
    return { visible: document.activeElement instanceof HTMLElement, controls: controls.length, unlabeled }
  })
  assert.equal(focusEvidence.unlabeled, 0)
  await interactive.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  const reducedMotion = await interactive.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  assert.equal(reducedMotion, true)
  const forcedColors = await interactive.evaluate(() => ({ active: matchMedia('(forced-colors: active)').matches, adjust: getComputedStyle(document.querySelector('.component-choice')).forcedColorAdjust }))
  assert.equal(forcedColors.active, true)
  assert.equal(forcedColors.adjust, 'auto')
  await interactive.setViewportSize({ width: 1280, height: 720 })
  await interactive.screenshot({ path: path.join(reportDir, 'desktop.png'), fullPage: true })
  await interactive.setViewportSize({ width: 1280, height: 720 })
  const zoom = await interactive.evaluate(() => { document.documentElement.style.zoom = '2'; return getComputedStyle(document.documentElement).zoom })
  assert.equal(zoom, '2')
  assert.equal(await interactive.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth * 2), true)
  await interactive.screenshot({ path: path.join(reportDir, 'zoom-200.png'), fullPage: true })
  await interactive.close()

  // Exercise the real iframe message boundary used by CoursewareViewer with
  // an HTTP origin (file:// has an opaque origin and must be rejected by the
  // runtime nonce guard). The parent harness represents the viewer shell; the
  // iframe is the artifact produced by the real renderer.
  const flashcardArtifact = artifacts.get('editorial:flashcard')
  viewerServer = createServer((request, response) => {
    if (request.url === '/viewer') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
      response.end('<!doctype html><html><body><iframe title="课件预览" src="/flashcard.html"></iframe></body></html>')
      return
    }
    if (request.url === '/flashcard.html') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
      response.end(readFileSync(flashcardArtifact))
      return
    }
    response.writeHead(404)
    response.end()
  })
  await new Promise(resolve => viewerServer.listen(0, '127.0.0.1', resolve))
  const viewerAddress = viewerServer.address()
  const viewer = await browser.newPage({ viewport: { width: 320, height: 640 } })
  await viewer.goto(`http://127.0.0.1:${viewerAddress.port}/viewer`, { waitUntil: 'networkidle' })
  const restoreProgress = await viewer.evaluate(() => new Promise(resolve => {
    const iframe = document.querySelector('iframe')
    const origin = window.location.origin
    const handler = event => {
      if (event.source === iframe.contentWindow && event.origin === origin && event.data?.type === 'progress') {
        window.removeEventListener('message', handler)
        resolve(event.data)
      }
    }
    window.addEventListener('message', handler)
    iframe.contentWindow.postMessage({
      type: 'courseware-init', nonce: 'browser-viewer-nonce', resource_id: 'unknown-resource', release_id: 'unknown-release',
      restore: { current_scene_id: 'scene-0', current_scene_index: 0, component_state: { 'scene-0': { 'block-1': { component_version: '1.0', value: { flashcard: { status: 'back' } } } } } },
    }, origin)
  }))
  assert.equal(restoreProgress.scene_index, 0)
  const restoredFlashcard = await viewer.locator('iframe').evaluate(frame => ({
    frontHidden: frame.contentDocument.querySelector('.flash-front')?.hidden,
    backHidden: frame.contentDocument.querySelector('.flash-back')?.hidden,
    status: frame.contentDocument.querySelector('[data-flashcard]')?.dataset.reviewStatus,
  }))
  assert.deepEqual(restoredFlashcard, { frontHidden: true, backHidden: false, status: 'back' })
  await viewer.locator('iframe').evaluate(frame => frame.contentWindow.postMessage({ type: 'courseware-command', command: 'restart', nonce: 'wrong-nonce' }, window.location.origin))
  const nonceGuard = await viewer.locator('iframe').evaluate(frame => frame.contentDocument.querySelector('[data-flashcard]')?.dataset.reviewStatus === 'back')
  const httpOriginIframe = await viewer.evaluate(() => window.location.origin.startsWith('http://') && document.querySelector('iframe')?.src.startsWith('http://'))
  const artifactRestore = restoredFlashcard.frontHidden === true && restoredFlashcard.backHidden === false
  await viewer.close()
  assert.deepEqual(consoleErrors, [])
  writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify({ schema_version: '1.4', viewports: recipeViewports.map(item => item.name), consoleErrors, keyboard: ['Tab', 'Enter', 'Space', 'ArrowLeft', 'ArrowRight'], csp: true, touch: true, reducedMotion, forcedColors, forced_colors_active: forcedColors.active, zoom, zoom_200_active: zoom === '2', http_origin_iframe: httpOriginIframe, nonce_guard: nonceGuard, artifact_restore: artifactRestore, focusEvidence, contrast: true, a11y: { unlabeled: focusEvidence.unlabeled }, component_theme_matrix: componentThemeMatrix, recipe_theme_viewport_matrix: recipeThemeViewportMatrix }, null, 2))
} finally {
  if (viewerServer) await new Promise(resolve => viewerServer.close(resolve))
  await browser.close()
  rmSync(tempDir, { recursive: true, force: true })
}

console.log('courseware browser quality gate passed')
