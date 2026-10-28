import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = path.resolve(frontend, '../output/test-runs/onboarding-t34')
mkdirSync(output, { recursive: true })
const server = await createServer({ root: frontend, configFile: path.join(frontend, 'vite.config.js'), cacheDir: path.join(output, 'vite-cache'), optimizeDeps: { entries: ['tests/fixtures/onboardingContinuity.html'] }, server: { host:'127.0.0.1', port:0, strictPort:false, open:false, proxy:{} } })
const direction = { track_id:'rag', knowledge_base_id:'kb-rag', name:'RAG 工程链路培训', metadata:{ available:true, document_count:6, skill_node_count:13 } }
const questions = [ { question_id:'known', title:'你了解哪些能力节点？', type:'multiple_choice', validation:{ exclusive_option_values:['都不了解'] }, options:['RAG', 'Embedding', '都不了解'] }, { question_id:'goal', title:'补充学习目标', type:'text' } ]
const diagnostic = { question_id:'diag', question_type:'multiple_choice', question:'以下概念了解哪些？', options:['检索', '增强', '都不了解'] }
const profile = (id, extra = {}) => ({ learner_id:id, user_id:'account-a', knowledge_base_id:'kb-rag', profile_version:1, skill_level:'初级', learning_preferences:{ metadata:{ onboarding:{ learning_direction_id:'rag' } } }, ...extra })
let browser
const errors = [], unexpected = [], writes = []
const state = { profiles:[], deletionFails:false, active:false, delay:0, incomplete:false, sequence:0, pages:[], questionsFail:false, profileReadFails:false }
try {
  await server.listen()
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch(browserOptions('TEST_BROWSER_CHANNEL'))
  const context = await browser.newContext({ viewport:{ width:1393, height:900 } })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), method = route.request().method()
    if (url.origin !== origin) { unexpected.push(url.href); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const send = (data, status=200) => route.fulfill({ status, contentType:'application/json', body:JSON.stringify(data) })
    const body = route.request().postDataJSON()
    if (method !== 'GET') writes.push({ method, path:url.pathname, body })
    if (url.pathname === '/api/knowledge/domains') return send({ domains:[ { domain_id:'ai_application', name:'AI 应用开发', tracks:[direction] }, { domain_id:'industrial_internet', name:'工业互联网', tracks:[] }, { domain_id:'cyber_security', name:'网络安全', tracks:[] } ] })
    if (url.pathname === '/api/onboarding/questions') { if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay)); return state.questionsFail ? send({ message:'模拟问卷不可用' },500) : send({ questions }) }
    if (url.pathname === '/api/profiles/') {
      const n = Number(url.searchParams.get('page') || 1); state.pages.push(n)
      return send({ items:state.incomplete ? [] : state.profiles.slice((n-1)*100,n*100), total:state.incomplete ? 1 : state.profiles.length })
    }
    if (url.pathname.startsWith('/api/profiles/')) {
      const id = decodeURIComponent(url.pathname.split('/').at(-1))
      const found = state.profiles.find(item => item.learner_id === id)
      if (method === 'DELETE') {
        if (state.deletionFails) return send({ message:'模拟删除失败，原记录保留' }, 500)
        state.profiles = state.profiles.filter(item => item.learner_id !== id)
        return send({ status:'success', message:'deleted' })
      }
      if (state.profileReadFails) return send({ message:'模拟读取失败' },503)
      return found ? send(found) : send({ message:'not found' },404)
    }
    if (url.pathname === '/api/onboarding/initial-profile') {
      const created = profile(`account-a__rag__${++state.sequence}`)
      state.profiles.push(created)
      return send({ learner_id:created.learner_id, profile:created, diagnostic_questions:[diagnostic] })
    }
    if (url.pathname === '/api/diagnosis/submit') {
      const current = state.profiles.find(item => item.learner_id === body.learner_id); current.profile_version++
      return send({ ability_level:'初级', initial_diagnostic_status:'final', diagnostic_result_id:'diag-result', weak_points:['RAG'], strong_points:[], knowledge_states:{} })
    }
    if (url.pathname === '/api/generate/jobs' && method === 'POST') return send({ run_id:'mock-run', job_status:'queued', learner_id:body.learner_id })
    if (url.pathname === '/api/generate/jobs') return send({ items:state.active ? [{ job_status:'running' }] : [] })
    if (url.pathname === '/api/resources/courseware/jobs') return send({ items:[] })
    if (url.pathname === '/api/skills/nodes') return send({ nodes:[] })
    unexpected.push(url.pathname)
    return send({ message:'unexpected fixture API' },500)
  })
  const visit = async () => {
    await page.goto(`${origin}/tests/fixtures/onboardingContinuity.html`)
    await page.locator('.domain-stage-card .choice-card').first().waitFor()
    await page.waitForFunction(() => !document.querySelector('.domain-stage-card .choice-card')?.disabled)
  }
  const next = () => page.locator('.work-card').getByRole('button', { name:'下一步', exact:true }).click()
  const selectTrack = async () => {
    await page.locator('.domain-stage-card .choice-card').first().click(); await next()
    await page.locator('.track-stage-card .choice-card').first().click()
  }
  const navigate = path => page.evaluate(path => window.onboardingFixture.router.push(path), path)
  const clear = () => page.evaluate(() => { sessionStorage.clear(); localStorage.clear() })
  const writeCount = () => writes.filter(item => item.method === 'DELETE').length
  await visit()
  assert.equal(await page.locator('.domain-stage-card .choice-card:disabled').count(),2)
  await selectTrack(); await next(); await page.locator('.questionnaire-stage-card').waitFor()
  const known = page.locator('[data-question-id="known"]')
  await known.getByText('RAG',{ exact:true }).click()
  await known.getByText('都不了解',{ exact:true }).click()
  assert.equal(await known.getByRole('checkbox',{ name:'RAG',exact:true }).isChecked(),false)
  await known.getByText('Embedding',{ exact:true }).click()
  assert.equal(await known.getByRole('checkbox',{ name:'都不了解',exact:true }).isChecked(),false)
  await page.getByRole('textbox',{ name:'补充学习目标',exact:true }).fill('保留我的目标')
  await navigate('/other')
  await page.evaluate(() => window.onboardingFixture.store.setCurrentProfile({ learner_id:'other-profile', user_id:'account-a', knowledge_base_id:'other' }))
  await navigate('/learning/new'); await page.locator('.questionnaire-stage-card').waitFor()
  assert.equal(await page.getByRole('textbox',{ name:'补充学习目标',exact:true }).inputValue(),'保留我的目标')
  assert.equal(await known.getByRole('checkbox',{ name:'Embedding',exact:true }).isChecked(),true)
  await page.reload(); await page.locator('.questionnaire-stage-card').waitFor()
  assert.equal(await page.getByRole('textbox',{ name:'补充学习目标',exact:true }).inputValue(),'保留我的目标')
  await page.locator('.progress-card').first().click()
  await navigate('/other'); await navigate('/learning/new'); await page.locator('.domain-stage-card').waitFor()
  await page.locator('.progress-card').nth(2).click(); await page.locator('.questionnaire-stage-card').waitFor()
  assert.equal(await page.getByRole('textbox',{ name:'补充学习目标',exact:true }).inputValue(),'保留我的目标')
  await page.getByRole('button',{ name:'提交问卷',exact:true }).click(); await page.locator('.diagnosis-stage-card').waitFor()
  const diagnosis = page.locator('[data-question-id="diag"]')
  await diagnosis.getByText('都不了解',{ exact:true }).click()
  await diagnosis.getByText('检索',{ exact:true }).click()
  assert.equal(await diagnosis.getByRole('checkbox',{ name:'都不了解',exact:true }).isChecked(),false)
  await navigate('/other'); await navigate('/learning/new'); await page.locator('.diagnosis-stage-card').waitFor()
  assert.equal(await diagnosis.getByRole('checkbox',{ name:'检索',exact:true }).isChecked(),true)
  await page.reload(); await page.locator('.diagnosis-stage-card').waitFor()
  assert.equal(await diagnosis.getByRole('checkbox',{ name:'检索',exact:true }).isChecked(),true)
  await page.getByRole('button',{ name:'提交诊断',exact:true }).click(); await page.locator('.review-stage-card').waitFor()
  await page.reload(); await page.locator('.review-stage-card').waitFor()
  await page.getByRole('button',{ name:'生成并进入状态页',exact:true }).click(); await page.locator('.fixture-other').waitFor()
  assert.equal(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('onboarding_draft')).length),0)

  // Multi-page discovery and exact deletion target; unrelated/sibling records survive.
  await clear()
  state.profiles = [...Array.from({ length:100 },(_,i) => profile(`unrelated-${i}`, { knowledge_base_id:'elsewhere', learning_preferences:{} })),profile('older'),profile('newer')]
  await visit(); await selectTrack(); await next(); await page.getByRole('dialog',{ name:'此方向已有学习记录' }).waitFor()
  assert.ok(state.pages.includes(2))
  assert.equal(await page.locator('.existing-progress-list .el-radio').count(),2)
  assert.equal(await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).isDisabled(),true)
  await page.locator('.existing-progress-actions').getByRole('button',{ name:'取消',exact:true }).click()
  assert.equal(writeCount(),0)
  await next(); await page.locator('.existing-progress-list .el-radio').first().click()
  await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).click()
  await page.getByRole('button',{ name:'取消',exact:true }).last().click()
  assert.equal(writeCount(),0)
  state.active = true
  await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).click()
  await page.getByRole('button',{ name:'永久删除并重新开始',exact:true }).click()
  await page.getByText('该记录仍有进行中或状态未确认的任务，请等待任务结束后再重新开始',{ exact:true }).waitFor()
  assert.equal(writeCount(),0)
  state.active = false; state.deletionFails = true
  await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).click()
  await page.getByRole('button',{ name:'永久删除并重新开始',exact:true }).click()
  await page.getByText('模拟删除失败，原记录保留',{ exact:true }).waitFor()
  assert.equal(state.profiles.length,102)
  state.deletionFails = false
  state.questionsFail = true
  const writesBeforeQuestionsFail = writeCount()
  await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).click()
  await page.getByRole('button',{ name:'永久删除并重新开始',exact:true }).click()
  await page.getByText('模拟问卷不可用',{ exact:true }).waitFor()
  assert.equal(writeCount(),writesBeforeQuestionsFail)
  state.questionsFail = false
  const selectedId = await page.locator('.existing-progress-list input:checked').inputValue()
  await page.screenshot({ path:path.join(output,'old-progress-dialog.png'), animations:'disabled' })
  await page.getByRole('button',{ name:'删除所选记录并重新开始',exact:true }).click()
  await page.getByRole('button',{ name:'永久删除并重新开始',exact:true }).click()
  await page.locator('.questionnaire-stage-card').waitFor()
  assert.equal(state.profiles.length,101)
  assert.equal(state.profiles.some(item => item.learner_id === selectedId),false)
  assert.ok(writes.filter(item => item.method === 'DELETE').every(item => item.path === `/api/profiles/${selectedId}`))

  await clear(); state.profiles = [profile('continue')]
  await visit(); await selectTrack(); await next(); await page.locator('.existing-progress-list .el-radio').click()
  await page.getByRole('button',{ name:'保留进度并继续',exact:true }).click(); await page.locator('.fixture-other').waitFor()
  assert.equal(await page.evaluate(() => window.onboardingFixture.store.currentLearnerId),'continue')

  // Failed/incomplete read does not silently create another profile.
  await clear(); state.incomplete = true
  await visit(); await selectTrack(); await next()
  await page.getByText('学习记录未能完整读取，请稍后重试',{ exact:true }).waitFor()
  assert.equal(await page.locator('.questionnaire-stage-card').count(),0)
  state.incomplete = false; state.profiles = []; state.delay = 180
  await next(); await navigate('/other'); state.delay = 0
  await navigate('/learning/new'); await page.locator('.track-stage-card').waitFor()
  assert.equal(await page.locator('.questionnaire-stage-card').count(),0)
  // A missing/changed profile invalidates only downstream state, not cached questionnaire answers.
  await clear()
  const staleDraft = { version:1, userId:'account-a', savedAt:Date.now(), state:{ stage:'diagnosis', domainId:'ai_application', directionId:'rag', questionnaireLoaded:true, form:{ goal:'缓存答案', known:['RAG'] }, diagnosticAnswers:{ diag:['检索'] }, profile:profile('stale'), diagnosticQuestions:[diagnostic] } }
  await page.evaluate(draft => sessionStorage.setItem('onboarding_draft_v1:account-a',JSON.stringify(draft)), staleDraft)
  await page.reload(); await page.locator('.track-stage-card').waitFor()
  state.profiles = [profile('stale',{ profile_version:2 })]
  await page.evaluate(draft => sessionStorage.setItem('onboarding_draft_v1:account-a',JSON.stringify(draft)), staleDraft)
  await page.reload(); await page.locator('.track-stage-card').waitFor()
  await next(); await page.locator('.existing-progress-list').waitFor()
  await page.locator('.existing-progress-actions').getByRole('button',{ name:'取消',exact:true }).click()
  state.profiles = [profile('stale')]; state.profileReadFails = true
  await page.evaluate(draft => sessionStorage.setItem('onboarding_draft_v1:account-a',JSON.stringify(draft)), staleDraft)
  await page.reload(); await page.getByRole('button',{ name:'重试恢复',exact:true }).waitFor()
  assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem('onboarding_draft_v1:account-a')).state.form.goal),'缓存答案')
  state.profileReadFails = false
  await page.getByRole('button',{ name:'重试恢复',exact:true }).click(); await page.locator('.diagnosis-stage-card').waitFor()
  assert.equal(await page.locator('[data-question-id="diag"]').getByRole('checkbox',{ name:'检索',exact:true }).isChecked(),true)
  await page.evaluate(() => window.onboardingFixture.auth.setCurrentUser({ user_id:'account-b',display_name:'用户B' }))
  await page.locator('.domain-stage-card').waitFor()
  assert.equal(await page.locator('.choice-card.selected').count(),0)
  assert.equal(await page.evaluate(() => window.onboardingFixture.store.currentProfile),null)
  await page.evaluate(() => window.onboardingFixture.auth.setCurrentUser(null))
  assert.equal(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('onboarding_draft')).length),0)
  assert.deepEqual(unexpected,[]); assert.deepEqual(errors,[])
  writeFileSync(path.join(output,'browser.json'),JSON.stringify({ status:'passed', scope:'real Onboarding/Pinia/router, synthetic API only', checks:['disabled domains','bidirectional exclusive selections','navigation and reload drafts','earlier step draft','diagnostic round recovery','global context isolation','clear after generation/logout/account switch','paged old records','cancel twice','active task block','delete failure','questionnaire failure blocks deletion','exact selected deletion','keep old progress','incomplete read','late response','missing/changed profile','recovery network failure/retry'], writes, errors, unexpected },null,2))
  console.log('PASS four onboarding changes with isolated synthetic API; no real records accessed')
} finally { await browser?.close(); await server.close() }
