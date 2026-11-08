import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const fixtureDir = path.join(testDir, 'fixtures/courseware/content_review')
const manifest = JSON.parse(readFileSync(path.join(fixtureDir, 'manifest.json'), 'utf8'))
const reportDir = path.join(testDir, 'test-results/courseware-content-review')
mkdirSync(reportDir, { recursive: true })
const summary = { status: 'RUNNING', execution: manifest.execution, quality_gate: 'NOT_RUN_OFFLINE', cases: [], pageErrors: [] }
const server = createServer((request, response) => {
  const url = new URL(request.url, 'http://localhost')
  const entry = manifest.artifacts.find(a => a.group === url.searchParams.get('group'))
  if (url.pathname === '/harness' && entry) {
    response.setHeader('Content-Type', 'text/html; charset=utf-8')
    response.end(`<meta charset="utf-8"><iframe id="course" style="width:1280px;height:720px" src="/${entry.path}"></iframe><script>
      const frame=document.getElementById('course'), key='content-review-${entry.group}', context=${JSON.stringify(entry)};
      let restore=JSON.parse(localStorage.getItem(key)||'{"current_scene_index":0,"component_state":{}}');window.events=[];
      window.addEventListener('message',e=>{if(e.source!==frame.contentWindow||e.data?.type!=='learning_event')return;const event=e.data.event;window.events.push(event);
        if(event.event_type==='scene_viewed'){restore.current_scene_id=event.scene_id;restore.current_scene_index=event.state.scene_index}
        Object.entries(event.state.component_state||{}).forEach(([scene,values])=>{restore.component_state[scene]={...(restore.component_state[scene]||{}),...values}});localStorage.setItem(key,JSON.stringify(restore))});
      frame.onload=()=>frame.contentWindow.postMessage({type:'courseware-init',nonce:'fixture-content-review',resource_id:context.resource_id,release_id:context.release_id,restore},location.origin);
    </script>`)
  } else {
    const artifact = manifest.artifacts.find(a => '/' + a.path === url.pathname)
    if (!artifact) { response.writeHead(404); response.end(); return }
    response.setHeader('Content-Type', 'text/html; charset=utf-8')
    response.end(readFileSync(path.join(fixtureDir, artifact.path)))
  }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`
let browser
try {
  browser = await chromium.launch(browserOptions('COURSEWARE_BROWSER_CHANNEL'))
  for (const entry of manifest.artifacts) {
    const bytes = readFileSync(path.join(fixtureDir, entry.path))
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.artifact_sha256)
    assert.equal(entry.record_status, 'approved')
    const page = await browser.newPage({ viewport: { width: 1360, height: 860 } })
    page.on('pageerror', error => summary.pageErrors.push(error.message))
    await page.goto(`${origin}/harness?group=${entry.group}`)
    const frame = page.frameLocator('#course')
    await frame.locator('.scene.active').waitFor()
    const text = await frame.locator('body').textContent()
    for (const value of entry.approved_display_values) assert.ok(text.includes(value), `approved field missing: ${entry.group}`)
    assert.ok(!text.includes('错误候选'))
    assert.ok(!text.includes(entry.rejected_value))
    if (entry.group === 'review') {
      await frame.locator('[data-nav="1"]').click()
      const card = frame.locator(`[data-review-question-id="${entry.first_question.question_id}"]`)
      assert.ok((await card.textContent()).includes(entry.first_question.prompt))
      assert.equal(await card.locator('.review-answer').isVisible(), false)
      await card.locator('[data-review-reveal]').click()
      assert.ok((await card.locator('.review-answer').textContent()).includes(entry.first_question.reference_answer))
      await card.locator('[data-review-rating="uncertain"]').click()
      await page.waitForFunction(() => window.events.some(e => e.event_type === 'review_self_assessed'))
      await page.reload()
      await frame.locator('.scene.active[data-page-role="review_recall"]').waitFor()
      assert.equal(await card.locator('.review-answer').isVisible(), true)
      assert.equal(await card.locator('[data-review-rating="uncertain"]').getAttribute('aria-pressed'), 'true')
    } else {
      await frame.locator('[data-nav="1"]').click()
      assert.equal(await frame.locator('.scene.active').getAttribute('data-practice-json-phase'), 'prepare')
      const checks = frame.locator('.scene.active [data-check]')
      if (await checks.count()) {
        await checks.first().check()
        await page.waitForFunction(() => window.events.some(e => e.event_type === 'practice_step_toggled'))
      }
      await frame.locator('[data-nav="1"]').click()
      const step = frame.locator('.scene.active[data-practice-json-step="true"]')
      await step.waitFor()
      if (entry.group === 'practice_code') assert.ok((await step.textContent()).includes('assert value == 1'))
      else assert.equal(await step.locator('pre code').count(), 0)
      assert.ok((await step.textContent()).includes('核对输入版本并记录实际结果'))
      const sceneId = await step.getAttribute('data-scene-id')
      await page.waitForFunction(id => JSON.parse(localStorage.getItem('content-review-' + new URL(location.href).searchParams.get('group'))).current_scene_id === id, sceneId)
      await page.reload()
      await frame.locator(`.scene.active[data-scene-id="${sceneId}"]`).waitFor()
    }
    const screenshot = await page.screenshot({ path: path.join(reportDir, `${entry.group}.png`) })
    summary.cases.push({ group: entry.group, status: 'PASS', artifact_sha256: entry.artifact_sha256, screenshot_sha256: createHash('sha256').update(screenshot).digest('hex') })
    await page.close()
  }
  assert.deepEqual(summary.pageErrors, [])
  summary.status = 'PASS'
} catch (error) {
  summary.status = 'FAIL'; summary.error = error.message
  throw error
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
  writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify(summary, null, 2))
}
