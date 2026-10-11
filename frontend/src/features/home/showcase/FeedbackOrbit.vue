<template>
  <section class="feature-world feedback-world">
    <div class="feature-hero">
      <div class="feature-intro">
        <div class="feature-kicker"><i />04 / FEEDBACK REROUTES LEARNING.</div>
        <h2 id="feedback-title" class="feature-title" tabindex="-1">反馈，<br /><em>让学习路线转折。</em></h2>
        <p>正式测评更新掌握状态。<br />补前置、纠错巩固，再决定往哪里走。</p>
        <div class="feedback-rule-options" @focusin="holdFocus" @focusout="releaseFocus">
          <button v-for="(rule, index) in rules" :key="rule.code" type="button" :aria-label="'查看反馈规则：' + rule.label" :aria-pressed="scenario === index" @click="chooseRule(index, $event)">{{ rule.label }}<small>{{ rule.range }}</small></button>
        </div>
        <div class="feedback-demo-controls">
          <button v-if="!reducedMotion" type="button" class="feedback-playback" :aria-label="userPaused ? '继续演示' : '暂停演示'" @click="togglePlayback"><el-icon aria-hidden="true"><VideoPlay v-if="userPaused" /><VideoPause v-else /></el-icon>{{ userPaused ? '继续演示' : '暂停演示' }}</button>
          <span class="feedback-loop-label"><i :class="{ 'is-playing': running }" />{{ reducedMotion ? '静态展示' : '自动循环' }}<small v-if="!reducedMotion">12s / LOOP</small></span>
        </div>
        <p class="feedback-status" data-feedback-status>{{ status }}</p>
        <div class="feature-demo-note"><el-icon aria-hidden="true"><InfoFilled /></el-icon>项目机制示意 · A、B 为抽象学习节点</div>
      </div>
      <div ref="workbench" class="feature-scene feedback-workbench" :class="{ 'is-playing': running, 'is-static': reducedMotion }" :data-rule="activeRule.code" :data-phase="selected" :data-cycle="cycle" :data-playing="running" @focusin="holdFocus" @focusout="releaseFocus">
        <div class="feedback-scene-heading"><span>ADAPTIVE LEARNING / ROUTE REVISION</span><span>反馈 → 转折 → 确认</span></div>
        <div class="feedback-sequence">
          <button class="feedback-observation feedback-stage" type="button" data-feedback-step="0" aria-label="查看反馈步骤：测评依据" aria-describedby="feedback-condition" :aria-pressed="selected === 0" @click="chooseStep(0, $event)">
            <span class="feedback-stage-number" aria-hidden="true">01</span>
            <div class="feedback-stage-body observation-body"><span class="feedback-step-label">ASSESS / 测评依据</span><strong id="feedback-condition">{{ activeRule.condition }}</strong><span class="observation-signal" aria-hidden="true"><i /><i /><i /><i /><i /></span></div>
          </button>
          <button class="feedback-training feedback-stage" :class="{ 'is-active': selected === 1 }" type="button" data-feedback-step="1" aria-label="查看反馈步骤：路线重排" aria-describedby="feedback-route-title feedback-route-description feedback-route-constraint" :aria-pressed="selected === 1" @click="chooseStep(1, $event)">
            <span class="feedback-stage-number" aria-hidden="true">02</span>
            <div class="feedback-stage-body route-body">
              <div class="feedback-route-heading"><div><span class="feedback-step-label">REROUTE / {{ activeRule.action }}</span><strong id="feedback-route-title">{{ activeRule.title }}</strong></div><span class="route-state" aria-hidden="true">{{ selected === 1 ? '调整建议' : '条件示意' }}</span></div>
              <div class="feedback-route-canvas">
                <svg viewBox="0 0 760 360" fill="none" preserveAspectRatio="none" aria-hidden="true">
                  <defs><linearGradient id="feedback-route-light" x1="380" y1="80" x2="585" y2="284" gradientUnits="userSpaceOnUse"><stop stop-color="#936335" /><stop offset=".5" stop-color="#bb681c" /><stop offset="1" stop-color="var(--sc-accent)" /></linearGradient><marker id="feedback-route-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="4" markerHeight="4" orient="auto"><path d="M1 1L6 4L1 7" stroke="#a55b16" stroke-width="1.5" fill="none" /></marker></defs>
                  <path d="M380 80H644" class="feedback-base-line" />
                  <path :d="activeRule.path" class="feedback-route-rail" />
                  <path ref="routePath" :d="activeRule.path" class="feedback-turn-line" pathLength="1" stroke="url(#feedback-route-light)" marker-end="url(#feedback-route-arrow)" />
                  <g class="feedback-turn-halo"><circle :cx="turnX" cy="165.75" r="22" /></g><circle :cx="turnX" cy="165.75" r="5" class="feedback-turn-point" />
                  <g ref="flowMarker" class="feedback-flow-marker"><circle r="9" class="feedback-flow-glow" /><circle r="3.5" /></g>
                </svg>
                <ol class="feedback-baseline"><li><span class="node-letter">A</span><span>学习节点 A<small>本轮学习节点</small></span></li><li><span>{{ activeRule.original }}</span><small>原路线</small></li></ol>
                <span class="feedback-turn-label">FEEDBACK<span>{{ activeRule.turn }}</span></span>
                <ol id="feedback-route-description" class="feedback-adjusted-route"><li v-for="item in activeRule.route" :key="item.name"><span class="node-letter" aria-hidden="true">{{ item.letter }}</span><span>{{ item.name }}<small>{{ item.note }}</small></span></li></ol>
              </div>
              <p id="feedback-route-constraint" class="feedback-route-constraint">{{ activeRule.constraint }}</p>
            </div>
          </button>
          <button class="feedback-verification feedback-stage" type="button" data-feedback-step="2" aria-label="查看反馈步骤：确认后学习" aria-describedby="feedback-confirmation" :aria-pressed="selected === 2" @click="chooseStep(2, $event)">
            <span class="feedback-stage-number" aria-hidden="true">03</span>
            <div class="feedback-stage-body verification-body"><span class="verification-icon" aria-hidden="true"><el-icon><CircleCheck /></el-icon></span><div id="feedback-confirmation"><span class="feedback-step-label">CONFIRM / 学习者选择</span><strong>确认方案后，才生成下一批资源。</strong><p>{{ activeRule.followup }}</p></div></div>
          </button>
        </div>
        <div class="feedback-progress" aria-hidden="true"><span v-for="(label, index) in stageLabels" :key="label" :class="{ 'is-current': selected === index, 'is-past': selected > index }"><i /><b>{{ '0' + (index + 1) }}</b>{{ label }}</span></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { VideoPlay, VideoPause, InfoFilled, CircleCheck } from '@element-plus/icons-vue'
// Formal feedback: learning_agents/feedback_policy_agent.py (60% / 80% with node blockers).
// Suggestions/confirmation: services/feedback/feedback.py; tier guards: learners/mastery.py.
// A is the current node; B is a conditional prerequisite or successor, never a learner record.
// A single subpath passes through the first card before reaching the second.
// Cards cover the internal section, so the signal never jumps between disconnected rails.
const returnPath = 'M380 130Q380 157 350 157H210Q175 157 175 192V284H457'
const rules = [
  { code: 'remediate', label: '补基础', range: '< 60% / 节点阻断', condition: '总分或任一知识点低于 60%', action: '回溯未掌握前置', turn: '先回补前置', original: '暂缓后续学习', path: returnPath, title: '先回补，再向前。', route: [{ letter: 'B', name: '学习节点 B', note: '未掌握的前置候选' }, { letter: 'A', name: '学习节点 A', note: '回到本轮目标' }], constraint: '若 B 是 A 未掌握的前置，先补 B，再回到 A；候选受实际先修关系约束。', followup: '选中低阶节点并确认后，才调整当前学习阶。' },
  { code: 'practice', label: '纠错巩固', range: '60%–< 80%', condition: '总分 60%–低于 80%，且无节点阻断', action: '保持主路径 · 定向巩固', turn: '围绕薄弱点巩固', original: '先巩固，再决定', path: returnPath, title: '路线不跳级，薄弱点再练。', route: [{ letter: '↺', name: '个性化纠错训练包', note: '本次测评待巩固节点' }, { letter: 'A', name: '学习节点 A', note: '新的分阶测试题验证' }], constraint: '纠错包只围绕本次测评覆盖的待巩固节点，配套分阶新题。', followup: '有可用前置候选时，也可选择补基础。' },
  { code: 'advance', label: '继续进阶', range: '≥ 80% · 无阻断', condition: '总分达到 80%，且无知识点低于 60%', action: '按先修条件推进', turn: '选择可学后继', original: '校验可学条件', path: returnPath, title: '条件满足，再走向下一步。', route: [{ letter: 'A', name: '学习节点 A', note: '完成前置条件' }, { letter: 'B', name: '学习节点 B', note: '已解锁且先修满足的后继' }], constraint: '只有本阶全部节点完成才解锁下一阶；B 须已解锁且前置满足。', followup: '推荐会重算；不会自动创建下一轮任务。' },
]
const props = defineProps({ active: { type: Boolean, default: true } })
const durations = [3000, 5000, 4000]
const stageLabels = ['测评依据', '路线重排', '选择确认']
const scenario = ref(0)
const selected = ref(0)
const cycle = ref(0)
const running = ref(false)
const userPaused = ref(false)
const reducedMotion = ref(false)
const focusHeld = ref(false)
const workbench = ref(null)
const routePath = ref(null)
const flowMarker = ref(null)
const activeRule = computed(() => rules[scenario.value])
// All rules share the same bend; its quadratic midpoint is t=.5.
const turnX = 183.75
const status = computed(() => reducedMotion.value ? '减少动态效果 · 三步静态展示' : userPaused.value ? '演示已暂停' : focusHeld.value ? '阅读时暂停 · 移开焦点后继续' : !props.active ? '演示暂歇' : `${stageLabels[selected.value]} · 自动演示中`)
let timer = null
let remaining = durations[0]
let dueAt = 0
let mounted = false
let motionQuery
let frame = null
let pathLength = 0
const arrivalHold = 700
function paintTimeline(now = performance.now()) {
  if (!workbench.value || !routePath.value || !flowMarker.value) return
  const duration = durations[selected.value]
  const elapsed = duration - (timer === null ? remaining : Math.max(0, dueAt - now))
  const progress = Math.min(1, Math.max(0, elapsed / duration))
  const travel = reducedMotion.value || selected.value === 2 ? 1 : selected.value === 0 ? 0 : Math.min(1, elapsed / (durations[1] - arrivalHold))
  if (!pathLength) pathLength = routePath.value.getTotalLength()
  const point = routePath.value.getPointAtLength(pathLength * travel)
  routePath.value.style.strokeDashoffset = String(1 - travel)
  flowMarker.value.setAttribute('transform', `translate(${point.x} ${point.y})`)
  flowMarker.value.style.opacity = selected.value === 1 && !reducedMotion.value ? '1' : '0'
  workbench.value.dataset.routeProgress = travel.toFixed(5)
  workbench.value.dataset.phaseProgress = progress.toFixed(5)
  workbench.value.querySelectorAll('.feedback-progress > span > i').forEach((bar, index) => {
    bar.style.transform = `scaleX(${index < selected.value ? 1 : index === selected.value ? progress : 0})`
  })
}
function tick(now) {
  frame = null
  if (!running.value) return
  paintTimeline(now)
  frame = window.requestAnimationFrame(tick)
}
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
    timer = null
    remaining = 0
    paintTimeline()
    selected.value = (selected.value + 1) % durations.length
    if (selected.value === 0) cycle.value++
    remaining = durations[selected.value]
    syncPlayback()
  }, remaining)
  paintTimeline()
  if (frame === null) frame = window.requestAnimationFrame(tick)
}
function togglePlayback() { userPaused.value = !userPaused.value; syncPlayback() }
function clearPointerHold(event) { if (event?.detail > 0) focusHeld.value = false }
function chooseRule(index, event) { stopClock(); clearPointerHold(event); scenario.value = index; selected.value = 0; cycle.value = 0; remaining = durations[0]; pathLength = 0; syncPlayback(); nextTick(paintTimeline) }
function chooseStep(index, event) { stopClock(); clearPointerHold(event); selected.value = index; remaining = durations[index]; syncPlayback(); nextTick(paintTimeline) }
function holdFocus(event) { focusHeld.value = event.target.matches(':focus-visible'); syncPlayback() }
function releaseFocus(event) {
  const next = event.relatedTarget
  if (next instanceof Element && next.closest('.feedback-rule-options, .feedback-workbench')) return
  focusHeld.value = false
  syncPlayback()
}
function updateMotion() {
  stopClock()
  reducedMotion.value = motionQuery.matches
  if (reducedMotion.value) { selected.value = 1; remaining = durations[1] }
  syncPlayback()
  nextTick(paintTimeline)
}
watch(() => props.active, syncPlayback)
watch([scenario, selected], () => { pathLength = 0; paintTimeline() }, { flush: 'post' })
onMounted(() => {
  mounted = true
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionQuery.addEventListener('change', updateMotion)
  document.addEventListener('visibilitychange', syncPlayback)
  updateMotion()
})
onBeforeUnmount(() => {
  mounted = false
  stopClock()
  motionQuery?.removeEventListener('change', updateMotion)
  document.removeEventListener('visibilitychange', syncPlayback)
})
</script>

<style scoped>
.feedback-world::before { content: ''; position: absolute; z-index: -1; inset: 0 -5% 0 35%; pointer-events: none; background: radial-gradient(ellipse at 55% 50%, #ae742115, transparent 65%); }
.feedback-rule-options { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 28px; }
.feedback-rule-options button { display: grid; gap: 9px; padding: 12px 14px; min-height: 70px; border: 1px solid var(--sc-line); border-radius: 7px; background: var(--sc-surface); color: var(--sc-muted); font-size: 14px; text-align: left; transition: border-color 300ms, background-color 300ms; }
.feedback-rule-options small { font-size: 10px; }.feedback-rule-options button[aria-pressed="true"] { color: var(--sc-accent); border-color: var(--feedback-active-line); background: var(--sc-surface-raised); }.feedback-rule-options button:hover { border-color: var(--sc-accent); }
.feedback-demo-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 19px; margin-top: 28px; }
.feedback-playback { display: inline-flex; align-items: center; justify-content: center; gap: 9px; min-height: 44px; padding: 0 17px; border: 1px solid #b2946759; border-radius: 8px; color: var(--sc-accent); background: var(--sc-surface); font-size: 14px; transition: background-color 300ms; }.feedback-playback:hover { background: var(--sc-surface-raised); }.feedback-playback .el-icon { font-size: 17px; }
.feedback-loop-label { display: flex; align-items: center; gap: 8px; color: var(--sc-muted); font-size: 12px; }.feedback-loop-label small { color: var(--sc-muted); font: 10px Consolas, monospace; }.feedback-loop-label > i { width: 5px; height: 5px; border-radius: 50%; background: var(--sc-muted); }.feedback-loop-label > i.is-playing { background: var(--sc-accent); }
.feature-intro > .feedback-status { font-size: 13px; line-height: 1.7; margin-top: 17px; color: var(--sc-accent); min-height: 23px; }
.feedback-workbench { height: auto; --stage-gutter: 48px; }
.feedback-scene-heading { display: flex; justify-content: space-between; gap: 15px; padding-bottom: 16px; color: var(--sc-muted); font-size: 10px; }.feedback-scene-heading > span:first-child { font-family: Consolas, monospace; }
.feedback-sequence { display: grid; gap: 12px; position: relative; }.feedback-sequence::before { content: ''; position: absolute; left: 16px; top: 30px; bottom: 42px; width: 1px; background: linear-gradient(var(--sc-line), #dca15b65 45%, var(--sc-line)); }
.feedback-workbench .feedback-stage { position: relative; display: grid; grid-template-columns: var(--stage-gutter) minmax(0, 1fr); width: 100%; text-align: left; padding: 0; border: 0; border-radius: 0; background: transparent; color: var(--sc-ink); transition: color 450ms; }
.feedback-stage-number { position: relative; display: grid; place-items: center; justify-self: start; align-self: start; margin-top: 18px; width: 33px; height: 33px; border: 1px solid var(--sc-line); border-radius: 50%; background: var(--sc-bg); color: var(--sc-muted); font: 11px Consolas, monospace; transition: color 600ms, border-color 600ms, background-color 600ms, box-shadow 600ms; }
.feedback-stage[aria-pressed="true"] .feedback-stage-number { color: var(--sc-on-accent); background: var(--sc-accent); border-color: var(--sc-accent); box-shadow: 0 0 25px #ffbd5820; }
.feedback-stage-body { min-width: 0; border: 1px solid var(--sc-line); border-radius: 10px; transition: background-color 650ms, border-color 650ms, box-shadow 650ms; }
.feedback-stage[aria-pressed="true"] .feedback-stage-body { border-color: var(--feedback-active-line); }
.feedback-step-label { display: block; color: var(--sc-muted); font: 10px Consolas, monospace; line-height: 1.6; }
.observation-body { position: relative; padding: 15px 62px 15px 19px; min-height: 75px; background: var(--feedback-pending); }.observation-body strong { display: block; font-size: 15px; line-height: 1.6; font-weight: 550; margin-top: 7px; }
.feedback-observation[aria-pressed="true"] .observation-body { background: var(--feedback-active); box-shadow: 0 8px 24px var(--feedback-shadow); }
.observation-signal { position: absolute; right: 20px; bottom: 22px; display: flex; align-items: end; height: 24px; gap: 4px; }.observation-signal i { width: 3px; height: 10px; background: #bd9a6470; }.observation-signal i:nth-child(2) { height: 18px; }.observation-signal i:nth-child(3) { height: 24px; }.observation-signal i:nth-child(4) { height: 15px; }.feedback-observation[aria-pressed="true"] .observation-signal i { background: var(--sc-accent); }
.route-body { position: relative; overflow: hidden; padding: 18px 20px 15px; background: var(--feedback-pending); border-color: var(--sc-line); border-radius: 15px; box-shadow: none; }
.feedback-training.is-active .route-body { background-color: var(--feedback-active); border-color: var(--feedback-active-line); box-shadow: 0 20px 45px var(--feedback-shadow), 0 0 32px #eaa14f08; }.feedback-route-heading { display: flex; justify-content: space-between; gap: 12px; align-items: start; }.feedback-route-heading strong { display: block; margin-top: 6px; font-size: 24px; font-weight: 550; line-height: 1.4; color: var(--sc-muted); transition: color 650ms; }.route-state { flex-shrink: 0; border: 1px solid #e7b27338; border-radius: 4px; padding: 5px 7px; color: var(--sc-accent); font-size: 10px; }
.feedback-route-canvas { position: relative; height: 235px; margin-top: 10px; }.feedback-route-canvas > svg { pointer-events: none; }
.feedback-base-line { stroke: #95774760; stroke-width: 1; stroke-dasharray: 3 6; }.feedback-route-rail { stroke: #a378454a; stroke-width: 2; }.feedback-turn-line { stroke-width: 2; stroke-dasharray: 1; opacity: .3; transition: opacity 650ms; }.feedback-training.is-active .feedback-turn-line { opacity: .9; }.feedback-flow-marker { fill: #8d4613; opacity: 0; filter: drop-shadow(0 0 4px #b9713266); }.feedback-flow-glow { fill: #a55b1625; }.feedback-turn-halo { fill: #b9713212; stroke: #a55b1650; }.feedback-turn-point { fill: var(--sc-accent); filter: drop-shadow(0 0 7px #b9713244); }
.feedback-baseline, .feedback-adjusted-route { list-style: none; padding: 0; margin: 0; }
.feedback-baseline > li, .feedback-adjusted-route > li { position: absolute; display: flex; align-items: center; gap: 10px; border-radius: 8px; min-height: 66px; transform: translate(-50%, -50%); }
.feedback-baseline > li:first-child { top: 22.22%; left: 50%; width: 37%; padding: 11px; border: 1px solid #ccb18b5c; background: var(--sc-surface); }.node-letter { display: grid; place-items: center; flex-shrink: 0; width: 29px; height: 29px; border: 1px solid #a55b1654; border-radius: 7px; color: var(--sc-accent); font: 14px Consolas, monospace; background: #a55b160c; }
.feedback-baseline > li > span:last-child, .feedback-adjusted-route > li > span:last-child { min-width: 0; font-size: 14px; line-height: 1.5; color: var(--sc-ink); }.feedback-baseline small, .feedback-adjusted-route small { display: block; margin-top: 4px; color: var(--sc-muted); font-size: 10px; line-height: 1.5; }
.feedback-baseline > li:last-child { top: 22.22%; left: 86%; width: 24%; flex-direction: column; gap: 3px; min-height: 0; padding: 5px; background: var(--feedback-pending); }.feedback-baseline > li:last-child > span { color: var(--sc-muted); font-size: 11px; }.feedback-baseline > li:last-child small { font-size: 9px; margin: 0; }
.feedback-turn-label { position: absolute; --feedback-label-gap: 16px; right: calc(78.7171% + var(--feedback-label-gap)); top: 46.0417%; width: calc(21.2829% - var(--feedback-label-gap)); transform: translateY(-50%); text-align: right; display: grid; gap: 4px; color: var(--sc-accent); font: 10px Consolas, monospace; }.feedback-turn-label > span { font: 11px system-ui, sans-serif; color: var(--sc-muted); }

.feedback-adjusted-route > li { top: 78.89%; left: 23.03%; width: 34%; padding: 12px 10px; border: 1px solid #dbab697a; background: var(--feedback-node); box-shadow: 0 8px 22px var(--feedback-shadow); }.feedback-adjusted-route > li + li { left: 76.97%; }.feedback-training.is-active .feedback-adjusted-route > li:first-child .node-letter { background: var(--sc-accent); border-color: var(--sc-accent); color: var(--sc-on-accent); }
.feedback-route-constraint { margin: 3px 0 0; padding-top: 12px; border-top: 1px solid #dca15b29; color: var(--sc-muted); font-size: 11px; line-height: 1.8; }
.verification-body { display: flex; align-items: center; gap: 13px; padding: 15px 19px; min-height: 86px; border-style: dashed; background: var(--feedback-pending); }.feedback-verification[aria-pressed="true"] .verification-body { background: var(--feedback-active); border-style: solid; }.verification-icon { display: grid; place-items: center; flex-shrink: 0; width: 30px; height: 30px; border: 1px solid #c59f6755; border-radius: 50%; color: var(--sc-muted); transition: color 500ms, border-color 500ms; }.verification-icon .el-icon { font-size: 19px; }.feedback-verification[aria-pressed="true"] .verification-icon { color: var(--sc-accent); border-color: var(--sc-accent); }.verification-body strong { display: block; font-size: 15px; font-weight: 550; line-height: 1.6; margin-top: 5px; }.verification-body p { color: var(--sc-muted); font-size: 10px; line-height: 1.6; margin: 5px 0 0; }
.feedback-progress { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 17px 0 0 var(--stage-gutter); }.feedback-progress > span { position: relative; padding-top: 11px; color: var(--sc-muted); font-size: 10px; }.feedback-progress > span::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: #cda26735; }.feedback-progress b { margin-right: 7px; font: 10px Consolas, monospace; }.feedback-progress > span > i { position: absolute; top: 0; left: 0; width: 100%; height: 1px; background: var(--sc-accent); transform: scaleX(0); transform-origin: left; }.feedback-progress > span.is-current { color: var(--sc-accent); }.feedback-progress > span.is-past > i { transform: scaleX(1); }

/* Pending stages stay muted; the arrived route gains warm ivory and amber emphasis. */
.feedback-training.is-active .feedback-route-heading strong { color: var(--sc-accent); }
.feedback-baseline > li, .feedback-adjusted-route > li, .node-letter, .route-state { transition: color 650ms, background-color 650ms, border-color 650ms, box-shadow 650ms; }
.feedback-training:not(.is-active) .feedback-adjusted-route > li { background: var(--feedback-node-pending); border-color: var(--sc-line); box-shadow: none; }
.feedback-training:not(.is-active) .feedback-baseline > li:first-child { background: var(--feedback-node-pending); border-color: var(--sc-line); }
.feedback-training:not(.is-active) .node-letter, .feedback-training:not(.is-active) .route-state { color: var(--sc-muted); background: transparent; border-color: var(--sc-line); }
.feedback-training:not(.is-active) .feedback-turn-label { color: var(--sc-muted); }
.feedback-training:not(.is-active) .feedback-turn-point { fill: var(--sc-muted); opacity: .45; filter: none; }
.feedback-training:not(.is-active) .feedback-turn-halo { opacity: .35; }
@media (min-width: 1800px) { .feedback-workbench { --stage-gutter: 64px; }.feedback-sequence { gap: 17px; }.feedback-sequence::before { left: 21px; }.feedback-stage-number { width: 43px; height: 43px; font-size: 14px; margin-top: 22px; }.feedback-scene-heading { font-size: 13px; padding-bottom: 24px; }.feedback-step-label { font-size: 13px; }.observation-body { min-height: 100px; padding: 20px 70px 20px 26px; }.observation-body strong { font-size: 21px; }.route-body { padding: 24px 28px 21px; }.feedback-route-heading strong { font-size: 33px; }.route-state { font-size: 12px; padding: 7px 11px; }.feedback-route-canvas { height: 320px; margin-top: 16px; }.node-letter { width: 37px; height: 37px; font-size: 19px; }.feedback-baseline > li, .feedback-adjusted-route > li { min-height: 90px; gap: 15px; padding: 17px; }.feedback-baseline > li > span:last-child, .feedback-adjusted-route > li > span:last-child { font-size: 20px; }.feedback-baseline small, .feedback-adjusted-route small { font-size: 13px; }.feedback-baseline > li:last-child { min-height: 0; padding: 7px; gap: 2px; }.feedback-baseline > li:last-child > span { font-size: 14px; }.feedback-baseline > li:last-child small { font-size: 11px; }.feedback-turn-label { font-size: 12px; --feedback-label-gap: 20px; }.feedback-turn-label > span { font-size: 14px; }.feedback-route-constraint { font-size: 14px; padding-top: 16px; }.verification-body { min-height: 110px; padding: 21px 26px; }.verification-body strong { font-size: 21px; }.verification-body p { font-size: 13px; }.feedback-progress { margin-top: 22px; gap: 22px; }.feedback-progress > span, .feedback-progress b { font-size: 12px; }.feedback-rule-options button { font-size: 17px; padding: 16px 20px; }.feedback-rule-options small { font-size: 12px; }.feedback-playback { font-size: 17px; min-height: 51px; }.feedback-loop-label { font-size: 14px; }.feedback-loop-label small { font-size: 12px; } }
@media (max-width: 1100px) { .feedback-workbench { --stage-gutter: 40px; }.feedback-stage-number { width: 29px; height: 29px; font-size: 10px; }.feedback-sequence::before { left: 14px; }.feedback-scene-heading { font-size: 9px; gap: 6px; }.feedback-scene-heading > span:last-child { display: none; }.observation-body { padding: 13px 44px 13px 15px; min-height: 72px; }.observation-body strong { font-size: 14px; }.observation-signal { right: 13px; gap: 3px; }.feedback-step-label { font-size: 9px; }.route-body { padding: 15px; }.feedback-route-heading strong { font-size: 21px; }.route-state { font-size: 9px; padding: 4px 6px; }.feedback-route-canvas { height: 220px; }.feedback-baseline > li > span:last-child, .feedback-adjusted-route > li > span:last-child { font-size: 13px; }.node-letter { width: 24px; height: 27px; font-size: 13px; }.feedback-adjusted-route > li { gap: 7px; padding: 10px 8px; }.feedback-baseline small, .feedback-adjusted-route small { font-size: 9px; }.feedback-baseline > li:last-child > span { font-size: 10px; }.feedback-route-constraint { font-size: 10px; }.verification-body { gap: 10px; padding: 13px 15px; }.verification-body strong { font-size: 14px; }.feedback-rule-options { margin-top: 24px; gap: 7px; }.feedback-rule-options button { font-size: 13px; padding: 10px; } }
@media (min-width: 851px) and (max-width: 1100px) { .feedback-scene-heading { padding-bottom: 12px; }.feedback-sequence { gap: 10px; }.observation-body { min-height: 68px; padding-block: 11px; }.feedback-route-canvas { height: 200px; }.verification-body { min-height: 76px; padding-block: 10px; }.feedback-progress { margin-top: 12px; }.feedback-progress > span { padding-top: 9px; } }
@media (max-width: 850px) { .feedback-workbench { max-width: 650px; margin-inline: auto; }.feedback-route-canvas { height: 270px; }.feedback-scene-heading { font-size: 11px; }.feedback-step-label { font-size: 11px; }.observation-body strong, .verification-body strong { font-size: 16px; }.feedback-route-heading strong { font-size: 25px; }.feedback-route-constraint { font-size: 12px; }.feedback-baseline > li > span:last-child, .feedback-adjusted-route > li > span:last-child { font-size: 16px; }.feedback-baseline small, .feedback-adjusted-route small { font-size: 11px; }.verification-body p { font-size: 12px; } }
@media (max-width: 520px) { .feedback-rule-options { gap: 7px; }.feedback-rule-options button { font-size: 13px; padding: 10px 11px; }.feedback-rule-options small { font-size: 9px; }.feedback-loop-label small { font-size: 9px; }.feedback-workbench { --stage-gutter: 32px; }.feedback-stage-number { width: 24px; height: 24px; font-size: 9px; }.feedback-sequence::before { left: 11px; }.feedback-scene-heading { font-size: 9px; }.feedback-step-label { font-size: 10px; }.observation-body { padding: 15px; }.observation-body strong { font-size: 15px; }.observation-signal, .route-state { display: none; }.route-body { padding: 16px 12px; }.feedback-route-heading strong { font-size: 22px; }.feedback-route-canvas { height: 285px; margin-top: 12px; }.feedback-baseline > li:first-child { width: 51%; left: 39%; }.feedback-baseline > li:last-child { left: 85%; width: 31%; }.feedback-baseline > li > span:last-child, .feedback-adjusted-route > li > span:last-child { font-size: 13px; }.node-letter { width: 23px; height: 26px; font-size: 12px; }.feedback-baseline small, .feedback-adjusted-route small { font-size: 10px; }.feedback-adjusted-route > li { width: 46%; left: 24%; min-height: 86px; align-items: start; flex-direction: column; gap: 7px; padding: 11px; }.feedback-adjusted-route > li + li { left: 76%; }.feedback-turn-label { --feedback-label-gap: 10px; font-size: 9px; }.feedback-turn-label > span { font-size: 10px; }.feedback-route-constraint { font-size: 12px; }.verification-body { align-items: start; gap: 9px; padding: 15px 12px; }.verification-icon { width: 23px; height: 23px; }.verification-icon .el-icon { font-size: 16px; }.verification-body strong { font-size: 14px; }.verification-body p { font-size: 12px; }.feedback-progress { gap: 8px; }.feedback-progress b { margin-right: 4px; font-size: 9px; }.feedback-progress > span { font-size: 9px; } }
</style>
