<template>
  <section class="feature-world evidence-world">
    <div class="feature-hero">
      <div class="feature-intro">
        <div class="feature-kicker"><i />02 / CLAIMS, GROUNDED.</div>
        <h2 id="evidence-title" class="feature-title" tabindex="-1">不止给出结论，<br /><em>逐条追到依据。</em></h2>
        <p>Claim 独立抽取与判定。<br />关联证据，追溯到原始来源位置。</p>
        <div class="claim-rule-picker">
          <span class="rule-picker-label">查看判定规则</span>
          <div class="claim-rule-options" @focusin="holdFocus" @focusout="releaseFocus"><button v-for="(rule, index) in rules" :key="rule.code" type="button" :aria-label="'查看判定规则：' + rule.label" :aria-pressed="selected === index" @click="chooseRule(index, $event)">{{ rule.label }}</button></div>
        </div>
        <div class="claim-rule-detail" aria-live="polite"><span>{{ activeRule.code }}</span><h3>{{ activeRule.title }}</h3><p>{{ activeRule.detail }}</p></div>
        <div class="feature-demo-note"><el-icon aria-hidden="true"><InfoFilled /></el-icon>项目机制示意 · Claim 审核需开启</div>
      </div>
      <div ref="archive" class="feature-scene evidence-archive" :data-verdict="activeRule.code" :data-phase="phase" :data-playing="running" :data-cycle="cycle" :data-verdict-ready="verdictReady">
        <div class="trace-heading"><span>PROVENANCE / SOURCE EXPLORER</span><div class="trace-heading-actions"><span>陈述 → 证据 → 来源 → 判定</span><button v-if="!reducedMotion" type="button" class="trace-playback" :aria-label="userPaused ? '继续溯源演示' : '暂停溯源演示'" @click="togglePlayback"><el-icon aria-hidden="true"><VideoPlay v-if="userPaused" /><VideoPause v-else /></el-icon>{{ userPaused ? '继续' : '暂停' }}</button></div></div>
        <div ref="trace" class="evidence-trace">
          <svg class="trace-wiring" viewBox="0 0 760 430" fill="none" aria-hidden="true" preserveAspectRatio="none">
            <path d="M33 81V276Q33 300 55 300H247Q287 300 287 260V144Q287 122 310 122H387" class="trace-rail" :class="{ 'is-missing': selected === 1 }" />
            <path ref="tracePath" d="M33 81V276Q33 300 55 300H247Q287 300 287 260V144Q287 122 310 122H387" class="trace-signal" pathLength="1" :class="{ 'is-missing': selected === 1 }" />
            <circle cx="33" cy="81" r="4" class="trace-anchor is-reached" /><circle cx="33" cy="242" r="4" class="trace-anchor" :class="{ 'is-reached': phase >= 1 }" /><circle cx="387" cy="122" r="4" class="trace-anchor" :class="{ 'is-reached': phase >= 2 && selected !== 1 }" />
            <g ref="tracePoint" class="trace-light-point"><circle r="13" class="trace-light-halo" /><circle r="5" class="trace-light-core" /><circle r="2" class="trace-light-center" /></g>
          </svg>
          <svg ref="verdictWiring" class="verdict-wiring" fill="none" aria-hidden="true" preserveAspectRatio="none"><path ref="verdictRail" class="trace-rail" /><path ref="verdictPath" class="trace-signal" pathLength="1" /><g ref="finalLight" class="trace-light-point"><circle r="13" class="trace-light-halo" /><circle r="5" class="trace-light-core" /><circle r="2" class="trace-light-center" /></g></svg>
          <i ref="mobileLight" class="trace-mobile-light" aria-hidden="true" />
          <article class="trace-claim" :class="{ 'is-active': phase === 0, 'is-reached': phase >= 0 }"><span class="trace-step">01</span><div><span class="trace-code">CLAIM</span><h3>资源中的事实陈述</h3><p>原文区间 · 文本哈希</p></div></article>
          <span class="trace-connector trace-claim-link" :class="{ 'is-missing': selected === 1 }">{{ selected === 1 ? '未找到支持证据' : 'evidence_id 关联' }}</span>
          <article class="trace-evidence" :class="{ 'is-missing': selected === 1, 'is-active': phase === 1, 'is-reached': phase >= 1 }"><span class="trace-step">02</span><div><span class="trace-code">EVIDENCE</span><h3>{{ selected === 1 ? '当前证据中无依据' : '检索证据片段' }}</h3><p>{{ selected === 1 ? '不绑定 Evidence ID' : '仅允许证据白名单内的 ID' }}</p></div></article>
          <span class="trace-connector trace-source-link" :class="{ 'is-missing': selected === 1 }">{{ selected === 1 ? '不能补造来源' : 'Chunk 与文档版本定位' }}</span>
          <article class="trace-source" :class="{ 'is-missing': selected === 1, 'is-active': phase === 2 && selected !== 1, 'is-reached': phase >= 2 && selected !== 1 }" :data-source-state="selected === 1 ? 'unbound' : phase >= 2 ? 'located' : 'pending'">
            <div class="source-document-top"><span class="trace-code">03 / SOURCE LOCATOR</span><el-icon aria-hidden="true"><Document /></el-icon></div>
            <h3>定位原始来源</h3>
            <div class="source-excerpt" aria-hidden="true"><span>LOCATE THE EVIDENCE</span><i /><i /><div><b /><b /><b /></div><i /></div>
            <dl><div><dt>来源身份</dt><dd>知识库 · 文档版本 · Chunk</dd></div><div><dt>内容位置</dt><dd>章节 / 行号等来源定位</dd></div><div><dt>完整性</dt><dd>证据摘录哈希</dd></div></dl>
            <span class="source-schema-note">{{ selected === 1 ? '字段结构示意 · 无关联证据，不补造来源' : '字段结构示意' }}</span>
          </article>
        <article class="trace-verdict" :class="{ 'is-ready': verdictReady }" :data-reached="verdictReady" aria-label="第四步：独立判定">
          <div class="trace-final-content"><span class="trace-code">04 / INDEPENDENT VERDICT</span><div class="trace-verdict-result"><el-icon v-if="verdictReady" aria-hidden="true"><component :is="activeRule.icon" /></el-icon><strong>{{ verdictReady ? activeRule.label : '等待独立判定' }}</strong></div><div class="trace-final-meta"><p>{{ verdictReady ? activeRule.result : '溯源完成后，逐条核对' }}</p><small>机制示意，非实际审核结果</small></div></div>
        </article>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Document, CircleCheck, Warning, CircleClose, InfoFilled, VideoPlay, VideoPause } from '@element-plus/icons-vue'
// Verdict/evidence constraints: models/reviews/claims.py; locator fields: core/retrieval/evidence.py.
const selected = ref(0)
const rules = [
  { code: 'supported', label: '有证据支持', title: '证据能够支持这条陈述', detail: '支持判定必须绑定有效 Evidence ID，可沿关联找到来源位置。', result: '有效证据关联 · 可回到来源位置', icon: CircleCheck },
  { code: 'not_in_evidence', label: '当前无依据', title: '没有依据，不能补造来源', detail: '无依据判定不绑定 Evidence ID；不会用一个无关引用冒充支持。', result: '无有效 Evidence ID · 不补造来源', icon: Warning },
  { code: 'contradicted', label: '与来源矛盾', title: '引用存在，陈述仍可能错误', detail: '矛盾判定同样必须关联有效证据，以说明陈述与来源的冲突。', result: '有效证据关联 · 陈述与来源冲突', icon: CircleClose },
]
const activeRule = computed(() => rules[selected.value])
const props = defineProps({ active: { type: Boolean, default: true } })
const durations = [1800, 2600, 3400, 4200]
const verdictTravelTime = 1500
const phase = ref(0)
const running = ref(false)
const verdictReady = ref(false)
const cycle = ref(0)
const userPaused = ref(false)
const reducedMotion = ref(false)
const focusHeld = ref(false)
const archive = ref(null), trace = ref(null), tracePath = ref(null), tracePoint = ref(null), mobileLight = ref(null), finalLight = ref(null)
const verdictWiring = ref(null), verdictRail = ref(null), verdictPath = ref(null)
let timer = null, frame = null, remaining = durations[0], dueAt = 0, mounted = false
let pathLength = 0, verdictLength = 0, motionQuery, resizeObserver
let geometry = { claim: 0, evidence: 0, source: 0, verdict: 0 }
function updateGeometry() {
  if (!archive.value || !trace.value) return
  const traceBox = trace.value.getBoundingClientRect()
  const scaleX = trace.value.clientWidth / traceBox.width, scaleY = trace.value.clientHeight / traceBox.height
  const midpoint = selector => { const box = trace.value.querySelector(selector).getBoundingClientRect(); return (box.top + box.height / 2 - traceBox.top) * scaleY }
  const sourceBox = trace.value.querySelector('.trace-source').getBoundingClientRect()
  const verdictBox = archive.value.querySelector('.trace-verdict').getBoundingClientRect()
  geometry = { claim: midpoint('.trace-claim h3'), evidence: midpoint('.trace-evidence h3'), source: midpoint('.trace-source h3'), verdict: (verdictBox.top - traceBox.top) * scaleY }
  const width = trace.value.clientWidth, height = trace.value.clientHeight
  verdictWiring.value.setAttribute('viewBox', `0 0 ${width} ${height}`)
  const endX = (verdictBox.right - traceBox.left) * scaleX
  const endY = (verdictBox.top + verdictBox.height / 2 - traceBox.top) * scaleY
  const laneX = ((sourceBox.left + verdictBox.right) / 2 - traceBox.left) * scaleX
  let route
  if (selected.value === 1) {
    const wiring = trace.value.querySelector('.trace-wiring').getBoundingClientRect()
    const x = wiring.width * 33 / 760 * scaleX, y = wiring.height * 242 / 430 * scaleY
    const turnY = geometry.verdict - 18
    const radius = Math.min(12, Math.max(2, (laneX - endX) / 2))
    route = `M${x} ${y}V${turnY - 12}Q${x} ${turnY} ${x + 12} ${turnY}H${laneX - 12}Q${laneX} ${turnY} ${laneX} ${turnY + 12}V${endY - radius}Q${laneX} ${endY} ${laneX - radius} ${endY}H${endX}`
  } else {
    const startX = (sourceBox.left + sourceBox.width / 2 - traceBox.left) * scaleX
    const startY = (sourceBox.bottom - traceBox.top) * scaleY
    if (endY > startY + 6) {
      const radius = Math.min(18, (endY - startY) / 2)
      route = `M${startX} ${startY}V${endY - radius}Q${startX} ${endY} ${startX - radius} ${endY}H${endX}`
    } else {
      const bottomY = startY + 26
      route = `M${startX} ${startY}V${bottomY - 10}Q${startX} ${bottomY} ${startX - 10} ${bottomY}H${laneX + 10}Q${laneX} ${bottomY} ${laneX} ${bottomY - 10}V${endY + 10}Q${laneX} ${endY} ${laneX - 10} ${endY}H${endX}`
    }
  }
  verdictRail.value.setAttribute('d', route)
  verdictPath.value.setAttribute('d', route)
  verdictLength = verdictPath.value.getTotalLength()
  paintTimeline()
}
function paintTimeline(now = performance.now()) {
  if (!archive.value || !tracePath.value) return
  if (!pathLength) pathLength = tracePath.value.getTotalLength()
  const elapsed = durations[phase.value] - (timer === null ? remaining : Math.max(0, dueAt - now))
  const progress = Math.min(1, Math.max(0, elapsed / durations[phase.value]))
  const evidenceFraction = 161 / pathLength
  const first = Math.min(1, elapsed / (durations[1] - 400))
  const second = Math.min(1, elapsed / (durations[2] - 600))
  const full = selected.value !== 1
  const travel = reducedMotion.value || phase.value === 3 ? (full ? 1 : evidenceFraction) : phase.value === 0 ? 0 : phase.value === 1 ? evidenceFraction * first : full ? evidenceFraction + (1 - evidenceFraction) * second : evidenceFraction
  const point = tracePath.value.getPointAtLength(pathLength * travel)
  tracePath.value.style.strokeDashoffset = String(1 - travel)
  tracePoint.value.setAttribute('transform', `translate(${point.x} ${point.y})`)
  tracePoint.value.style.opacity = !reducedMotion.value && phase.value < 3 ? '1' : '0'
  const mobileY = phase.value === 0 ? geometry.claim : phase.value === 1 ? geometry.claim + (geometry.evidence - geometry.claim) * first : full ? geometry.evidence + (geometry.source - geometry.evidence) * (phase.value >= 3 ? 1 : second) : geometry.evidence
  mobileLight.value.style.transform = `translateY(${mobileY}px)`
  mobileLight.value.style.opacity = !reducedMotion.value && phase.value < 3 ? '1' : '0'
  const verdictProgress = reducedMotion.value ? 1 : phase.value === 3 ? Math.min(1, elapsed / verdictTravelTime) : 0
  const finalPoint = verdictPath.value.getPointAtLength(verdictLength * verdictProgress)
  verdictPath.value.style.strokeDashoffset = String(1 - verdictProgress)
  finalLight.value.setAttribute('transform', `translate(${finalPoint.x} ${finalPoint.y})`)
  finalLight.value.style.opacity = !reducedMotion.value && phase.value === 3 && elapsed < verdictTravelTime + 300 ? '1' : '0'
  if (phase.value === 3) {
    mobileLight.value.style.transform = `translateY(${(full ? geometry.source : geometry.evidence) + (geometry.verdict - (full ? geometry.source : geometry.evidence)) * verdictProgress}px)`
    mobileLight.value.style.opacity = !reducedMotion.value && verdictProgress < 1 ? '1' : '0'
  }
  verdictReady.value = phase.value === 3 && verdictProgress === 1
  archive.value.dataset.traceProgress = travel.toFixed(5)
  archive.value.dataset.phaseProgress = progress.toFixed(5)
  archive.value.dataset.verdictProgress = verdictProgress.toFixed(5)
}
function tick(now) { frame = null; if (!running.value) return; paintTimeline(now); frame = window.requestAnimationFrame(tick) }
function stopClock() {
  if (timer !== null) { window.clearTimeout(timer); timer = null; remaining = Math.max(0, dueAt - performance.now()) }
  if (frame !== null) { window.cancelAnimationFrame(frame); frame = null }
  running.value = false
  paintTimeline()
}
function syncPlayback() {
  if (!mounted || !props.active || document.hidden || reducedMotion.value || focusHeld.value || userPaused.value) { stopClock(); return }
  if (timer !== null) return
  running.value = true
  dueAt = performance.now() + remaining
  timer = window.setTimeout(() => {
    timer = null; remaining = 0; paintTimeline()
    if (phase.value === 3) { cycle.value++; phase.value = 0; verdictReady.value = false } else phase.value++
    remaining = durations[phase.value]; syncPlayback()
  }, remaining)
  paintTimeline()
  if (frame === null) frame = window.requestAnimationFrame(tick)
}
function restart() { stopClock(); phase.value = 0; cycle.value = 0; verdictReady.value = false; remaining = durations[0]; syncPlayback(); nextTick(paintTimeline) }
function chooseRule(index, event) {
  if (event?.detail > 0) focusHeld.value = false
  selected.value = index
  if (reducedMotion.value) { stopClock(); phase.value = 3; remaining = 0; nextTick(updateGeometry); return }
  restart()
  nextTick(updateGeometry)
}
function togglePlayback() { userPaused.value = !userPaused.value; syncPlayback() }
function holdFocus(event) { focusHeld.value = event.target.matches(':focus-visible'); syncPlayback() }
function releaseFocus(event) { if (event.relatedTarget instanceof Element && event.relatedTarget.closest('.claim-rule-options')) return; focusHeld.value = false; syncPlayback() }
function updateMotion() { stopClock(); reducedMotion.value = motionQuery.matches; if (reducedMotion.value) { phase.value = 3; remaining = 0 } else { phase.value = 0; remaining = durations[0]; verdictReady.value = false }; syncPlayback(); nextTick(paintTimeline) }
watch(() => props.active, syncPlayback)
watch([selected, phase], () => paintTimeline(), { flush: 'post' })
onMounted(() => {
  mounted = true
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionQuery.addEventListener('change', updateMotion)
  document.addEventListener('visibilitychange', syncPlayback)
  resizeObserver = new ResizeObserver(updateGeometry)
  resizeObserver.observe(archive.value)
  resizeObserver.observe(trace.value.querySelector('.trace-source'))
  resizeObserver.observe(trace.value.querySelector('.trace-verdict'))
  updateGeometry(); updateMotion()
})
onBeforeUnmount(() => { mounted = false; stopClock(); resizeObserver?.disconnect(); motionQuery?.removeEventListener('change', updateMotion); document.removeEventListener('visibilitychange', syncPlayback) })
</script>

<style scoped>
.evidence-world::before { content: ''; position: absolute; z-index: -1; inset: 5% -10% 0 28%; background: radial-gradient(ellipse, #7ea77b19, transparent 65%); pointer-events: none; }
.claim-rule-picker { margin-top: 32px; }.rule-picker-label { color: var(--sc-muted); font-size: 13px; }.claim-rule-options { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }.claim-rule-options button { min-height: 44px; padding: 10px 14px; border: 1px solid var(--sc-line); border-radius: 6px; background: transparent; color: var(--sc-muted); font-size: 14px; transition: background-color 300ms, border-color 300ms; }.claim-rule-options button[aria-pressed="true"] { color: var(--sc-accent); border-color: var(--sc-accent); background: var(--sc-surface-raised); }.claim-rule-options button:hover { border-color: var(--sc-accent); }
.claim-rule-detail { margin-top: 26px; border-left: 1px solid #24674f55; padding-left: 18px; max-width: 390px; min-height: 134px; }.claim-rule-detail > span { color: var(--sc-accent); font: 12px Consolas, monospace; }.claim-rule-detail h3 { margin: 11px 0 0; font-size: 18px; font-weight: 550; }.claim-rule-detail p { margin: 10px 0 0; color: var(--sc-muted); font-size: 14px; line-height: 1.8; }
.evidence-archive { height: auto; padding: 18px 0 0; background: transparent; }
.trace-heading { position: relative; display: flex; justify-content: space-between; gap: 14px; padding-bottom: 20px; border-bottom: 1px solid var(--sc-line); color: var(--sc-muted); font-size: 11px; }.trace-heading > span:first-child { font-family: Consolas, monospace; }
.evidence-trace { position: relative; height: 525px; margin-top: 20px; }.trace-wiring { pointer-events: none; z-index: 0; height: 430px; }.verdict-wiring { pointer-events: none; z-index: 0; }
 .trace-rail { stroke: #31775a27; stroke-width: 1.5; }.trace-rail.is-missing { stroke-dasharray: 4 7; }
.trace-signal { stroke: #287454; stroke-width: 2; stroke-dasharray: 1; }.trace-signal.is-missing { opacity: .7; }.trace-anchor { fill: #526a6040; transition: fill 650ms; }.trace-anchor.is-reached { fill: var(--sc-accent); }
.trace-light-point { pointer-events: none; transition: opacity 300ms; }.trace-light-halo { fill: #2a97642b; filter: blur(3px); }.trace-light-core { fill: #25825b; filter: drop-shadow(0 0 4px #3da57c); }.trace-light-center { fill: #f5fff7; }.trace-mobile-light { display: none; }
.trace-claim, .trace-evidence { position: absolute; left: 0; width: 39%; display: flex; gap: 18px; align-items: start; padding: 0 12px; z-index: 1; }.trace-claim { top: 21px; }.trace-evidence { top: 182px; }
.trace-step { padding-top: 27px; color: var(--sc-accent); font: 13px Consolas, monospace; }.trace-code { color: var(--sc-accent); font: 11px Consolas, monospace; line-height: 1.7; }.evidence-trace h3 { margin: 9px 0 0; font-size: 19px; font-weight: 550; line-height: 1.5; }.trace-claim p, .trace-evidence p { color: var(--sc-muted); font-size: 12px; line-height: 1.7; margin: 10px 0 0; }
.trace-connector { position: absolute; z-index: 1; font-size: 10px; line-height: 1.6; color: var(--sc-accent); padding: 4px 0; pointer-events: none; }.trace-claim-link { left: calc(4.35% + 19px); top: 122px; }.trace-source-link { left: 8%; top: 314px; }.is-missing.trace-connector { color: var(--sc-muted); }
.trace-source { position: absolute; z-index: 2; top: 14px; right: 0; width: 51%; min-height: 360px; padding: 22px; background: #fafcf6; border: 1px solid #a6bdaa; border-radius: 10px; box-shadow: 0 25px 50px #2a503512; transition: border-color 350ms; }
.trace-source::before { content: ''; position: absolute; inset: 0; z-index: -1; border: 1px solid #adbeaa70; background: transparent; border-radius: inherit; transform: translate(7px, 7px); }
.trace-source.is-missing { border-style: dashed; }.source-document-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.source-document-top .el-icon { color: var(--sc-accent); font-size: 22px; }
.trace-source h3 { margin-top: 19px; font-size: 28px; letter-spacing: -.04em; }.source-excerpt { margin: 20px 0; padding-block: 15px; border-block: 1px solid #2b67472b; }.source-excerpt > span { display: block; margin-bottom: 13px; color: #647b68; font: 9px Consolas, monospace; }.source-excerpt > i { display: block; height: 4px; margin-top: 8px; width: 83%; background: #627b6320; }.source-excerpt > i:nth-child(3) { width: 61%; }.source-excerpt > div { display: flex; gap: 6px; border-left: 2px solid #387657; padding: 12px 10px; margin-top: 9px; background: #3a885717; }.source-excerpt b { height: 5px; width: 30%; background: #3a765544; }.source-excerpt b:last-child { width: 18%; }
.trace-source dl { margin: 0; display: grid; gap: 13px; }.trace-source dl > div { display: grid; grid-template-columns: 65px minmax(0, 1fr); gap: 9px; align-items: start; }.trace-source dt { color: var(--sc-muted); font-size: 11px; }.trace-source dd { margin: 0; color: var(--sc-ink); font-size: 13px; line-height: 1.5; }.source-schema-note { display: block; margin-top: 20px; font: 10px system-ui, sans-serif; color: var(--sc-muted); }
 .trace-heading-actions { display: flex; align-items: center; padding-right: 76px; }.trace-playback { position: absolute; right: 0; top: -13px; min-height: 44px; min-width: 64px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; padding: 0 9px; border: 1px solid var(--sc-line); border-radius: 6px; color: var(--sc-accent); background: var(--sc-bg); font-size: 11px; transition: background-color 300ms; }.trace-playback:hover { background: var(--sc-surface-raised); }
.trace-claim h3, .trace-evidence h3, .trace-source h3 { color: var(--sc-muted); transition: color 650ms; }.trace-claim.is-reached h3, .trace-evidence.is-reached h3, .trace-source.is-reached h3 { color: var(--sc-ink); }
.trace-source { transition: border-color 650ms, box-shadow 650ms, background-color 650ms; }.trace-source.is-active { border-color: var(--sc-accent); background-color: #f5faf1; box-shadow: 0 20px 55px #2a50351c, 0 0 24px #317e5520; }.trace-source.is-missing { background: var(--sc-surface); box-shadow: none; }.trace-source.is-missing .source-excerpt > div { border-color: var(--sc-line); background: #627b6308; }.trace-source.is-missing .source-excerpt b { background: #627b6320; }
.trace-verdict { --verdict-color: var(--sc-accent); position: absolute; bottom: 0; left: 0; width: 43%; z-index: 3; display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; min-height: 145px; padding: 18px 14px; border: 1px solid var(--sc-line); border-radius: 10px; background: var(--sc-surface); color: var(--sc-muted); transition: border-color 750ms, background-color 750ms, box-shadow 750ms; }
.trace-verdict.is-ready { border-color: var(--verdict-color); background-color: #e7f0e5; box-shadow: 0 10px 35px #245c3b14; }.evidence-archive[data-verdict="contradicted"] .trace-verdict { --verdict-color: #954635; }.evidence-archive[data-verdict="contradicted"] .trace-verdict.is-ready { background-color: #f6ede7; }.evidence-archive[data-verdict="not_in_evidence"] .trace-verdict { --verdict-color: #855629; }.evidence-archive[data-verdict="not_in_evidence"] .trace-verdict.is-ready { background-color: #f4eee2; }
.trace-final-content { min-width: 0; }.trace-final-content > .trace-code { font-size: 10px; color: var(--sc-muted); }.trace-verdict-result { display: flex; align-items: center; gap: 8px; margin-top: 5px; min-height: 33px; }.trace-verdict-result .el-icon { font-size: 23px; color: var(--verdict-color); }.trace-verdict-result strong { color: var(--sc-muted); font-size: 24px; line-height: 1.35; font-weight: 600; transition: color 750ms; }.trace-verdict.is-ready .trace-verdict-result strong { color: var(--verdict-color); }.trace-final-meta { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 5px 12px; margin-top: 6px; }.trace-final-meta p { margin: 0; font-size: 11px; line-height: 1.5; }.trace-final-meta small { font-size: 9px; line-height: 1.5; }
@media (min-width: 1800px) { .evidence-trace { height: 650px; }.trace-wiring { height: 530px; }.trace-claim { top: 35px; }.trace-evidence { top: 236px; }.trace-step { font-size: 16px; padding-top: 35px; }.trace-code { font-size: 13px; }.evidence-trace h3 { font-size: 25px; }.trace-claim p, .trace-evidence p { font-size: 15px; }.trace-claim-link { top: 156px; }.trace-source-link { top: 389px; }.trace-connector { font-size: 12px; }.trace-source { top: 28px; padding: 28px; min-height: 447px; }.trace-source h3 { font-size: 38px; }.source-excerpt { margin-block: 24px; }.source-excerpt > span { font-size: 11px; }.trace-source dl > div { grid-template-columns: 80px minmax(0, 1fr); }.trace-source dt { font-size: 13px; }.trace-source dd { font-size: 16px; }.source-schema-note { font-size: 12px; }.trace-heading { font-size: 13px; }.claim-rule-options button { font-size: 16px; padding: 12px 16px; }.claim-rule-detail h3 { font-size: 21px; }.claim-rule-detail p { font-size: 16px; }.claim-rule-detail { min-height: 154px; }.trace-verdict { grid-template-columns: minmax(0, 1fr); padding: 23px 20px; min-height: 175px; }.trace-final-content > .trace-code { font-size: 12px; }.trace-verdict-result strong { font-size: 31px; }.trace-final-meta p { font-size: 14px; }.trace-final-meta small { font-size: 11px; } }
@media (max-width: 1100px) { .trace-heading { font-size: 9px; }.trace-claim, .trace-evidence { gap: 9px; padding-inline: 0; width: 43%; }.evidence-trace h3 { font-size: 16px; }.trace-step { font-size: 11px; }.trace-claim p, .trace-evidence p { font-size: 11px; }.trace-source { width: 50%; padding: 17px; }.trace-source h3 { font-size: 24px; }.trace-source dl > div { grid-template-columns: 53px minmax(0, 1fr); gap: 6px; }.trace-source dd { font-size: 12px; }.trace-connector { font-size: 9px; }.trace-verdict { grid-template-columns: minmax(0, 1fr); padding: 15px 12px; min-height: 140px; }.trace-final-content > .trace-code { font-size: 9px; }.trace-verdict-result strong { font-size: 20px; }.trace-verdict-result { min-height: 27px; }.claim-rule-picker { margin-top: 24px; }.claim-rule-detail { margin-top: 22px; } }
@media (min-width: 851px) and (max-width: 1100px) { .evidence-trace { height: 510px; }.trace-wiring { height: 405px; }.trace-source-link { top: 300px; } }
@media (max-width: 850px) { .evidence-archive { max-width: 650px; margin-inline: auto; }.evidence-trace { height: 555px; }.trace-wiring { height: 480px; }.trace-claim { top: 34px; }.trace-evidence { top: 214px; }.trace-claim-link { top: 144px; }.trace-source-link { top: 352px; }.trace-source { top: 34px; }.trace-heading { font-size: 11px; }.trace-claim h3, .trace-evidence h3 { font-size: 18px; }.trace-claim p, .trace-evidence p { font-size: 12px; } }
@media (max-width: 520px) { .trace-heading { font-size: 9px; }.trace-heading-actions > span { display: none; }.evidence-trace { height: auto; display: grid; grid-template-columns: 1fr; gap: 15px; padding-left: 22px; border-left: 1px solid #39775955; }.trace-wiring, .verdict-wiring { display: none; }.trace-claim, .trace-evidence, .trace-source, .trace-connector { position: relative; inset: auto; width: 100%; }.trace-claim, .trace-evidence { padding: 4px 0; gap: 12px; }.trace-claim h3, .trace-evidence h3 { font-size: 20px; }.trace-connector { justify-self: start; width: auto; padding-left: 31px; font-size: 11px; }.trace-source { margin-top: 3px; width: calc(100% - 13px); min-height: 350px; padding: 24px; transform: none; }.trace-source h3 { font-size: 27px; }.trace-source dl > div { grid-template-columns: 1fr; gap: 5px; }.trace-source dd { font-size: 14px; }.trace-mobile-light { position: absolute; display: block; top: 0; left: -4px; width: 7px; height: 7px; border-radius: 50%; background: #25825b; box-shadow: 0 0 10px #2b986c77; pointer-events: none; }.trace-verdict { position: relative; bottom: auto; left: auto; width: calc(100% - 13px); margin-top: 9px; grid-template-columns: minmax(0, 1fr); padding: 15px 12px; }.trace-verdict-result strong { font-size: 22px; } }
</style>
