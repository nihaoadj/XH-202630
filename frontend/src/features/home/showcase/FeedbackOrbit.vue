<template>
  <section class="feature-world feedback-world">
    <div class="feature-hero feedback-hero">
      <div class="feature-intro">
        <div class="feature-kicker"><i />04 / FEEDBACK REROUTES LEARNING.</div>
        <h2 id="feedback-title" class="feature-title" tabindex="-1">每一次反馈，<br /><em>都让方向更清晰。</em></h2>
        <p class="feedback-description"><span>以反馈，校准学习的方向</span>从真实的掌握程度出发，<br />为下一步学习，找到恰当的路径。</p>
      </div>

      <div class="feature-scene feedback-branches" :class="{ 'is-active': active, 'has-selection': selectedRoute !== null }" :data-selected="selectedRoute" role="group" aria-label="测评反馈后的三种学习路线">
        <div class="feedback-scene-heading"><span>一次测评 · 不同的学习方向</span></div>

        <div class="feedback-diagram">
          <article class="feedback-origin">
            <span class="feedback-card-kicker">共同起点</span>
            <div class="feedback-origin-content">
              <span class="feedback-node-letter" aria-hidden="true">A</span>
              <span><strong>完成当前学习并参加测评</strong><small>更新掌握状态，作为后续路线的共同依据</small></span>
            </div>
          </article>

          <div ref="splitElement" class="feedback-split" aria-hidden="true">
            <svg :viewBox="`0 0 ${splitSize.width} ${splitSize.height}`">
              <defs><marker id="feedback-branch-arrow" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M2 1L6 4L2 7" /></marker></defs>
              <path class="feedback-wire feedback-wire-trunk" :d="paths.trunk" />
              <path class="feedback-wire feedback-wire-left" :d="paths.left" marker-end="url(#feedback-branch-arrow)" />
              <path class="feedback-wire feedback-wire-middle" :d="paths.middle" marker-end="url(#feedback-branch-arrow)" />
              <path class="feedback-wire feedback-wire-right" :d="paths.right" marker-end="url(#feedback-branch-arrow)" />
              <path class="feedback-flow feedback-flow-left" data-route="remediate" :style="flowStyle('remediate')" :d="paths.remediate" />
              <path class="feedback-flow feedback-flow-middle" data-route="practice" :style="flowStyle('practice')" :d="paths.practice" />
              <path class="feedback-flow feedback-flow-right" data-route="advance" :style="flowStyle('advance')" :d="paths.advance" />
            </svg>
            <span class="feedback-wire-joint" />
          </div>

          <div class="feedback-branch-grid">
            <article class="feedback-route feedback-route-remediate" :class="{ 'is-selected': selectedRoute === 'remediate', 'is-flowing': isFlowing('remediate') }">
              <header>
                <span class="feedback-route-index">路线 01</span>
                <h3><button type="button" :aria-pressed="selectedRoute === 'remediate'" @click="selectRoute('remediate')">补基础</button></h3>
                <p>总分或知识点低于 60%，或出现节点阻断</p>
              </header>
              <ol class="feedback-route-steps">
                <li><span class="feedback-node-letter" aria-hidden="true">B</span><span><strong>未掌握的前置</strong><small>先补足前置知识</small></span></li>
                <li><span class="feedback-node-letter" aria-hidden="true">A</span><span><strong>当前学习节点</strong><small>回到本轮目标继续</small></span></li>
              </ol>
            </article>

            <article class="feedback-route feedback-route-practice" :class="{ 'is-selected': selectedRoute === 'practice', 'is-flowing': isFlowing('practice') }">
              <header>
                <span class="feedback-route-index">路线 02</span>
                <h3><button type="button" :aria-pressed="selectedRoute === 'practice'" @click="selectRoute('practice')">纠错巩固</button></h3>
                <p>60%–低于 80%，且没有节点阻断</p>
              </header>
              <ol class="feedback-route-steps">
                <li><span class="feedback-node-letter" aria-hidden="true">↺</span><span><strong>个性化纠错训练</strong><small>围绕本轮薄弱节点</small></span></li>
                <li><span class="feedback-node-letter" aria-hidden="true">✓</span><span><strong>新题验证</strong><small>巩固后继续当前主路径</small></span></li>
              </ol>
            </article>

            <article class="feedback-route feedback-route-advance" :class="{ 'is-selected': selectedRoute === 'advance', 'is-flowing': isFlowing('advance') }">
              <header>
                <span class="feedback-route-index">路线 03</span>
                <h3><button type="button" :aria-pressed="selectedRoute === 'advance'" @click="selectRoute('advance')">继续进阶</button></h3>
                <p>总分达到 80%，且没有知识点低于 60%</p>
              </header>
              <ol class="feedback-route-steps">
                <li><span class="feedback-node-letter" aria-hidden="true">A</span><span><strong>完成当前学习阶</strong><small>满足本阶完成条件</small></span></li>
                <li><span class="feedback-node-letter" aria-hidden="true">B</span><span><strong>可学的后继节点</strong><small>先修条件满足后解锁</small></span></li>
              </ol>
            </article>
          </div>

          <div class="feedback-diagram-footer"><span>学习者确认方案后，才生成下一批资源。</span><small>机制示意 · A、B 为抽象学习节点</small></div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps({ active: { type: Boolean, default: true } })
const selectedRoute = ref(null)
const phase = ref(0)
const routeIndex = ref(0)
const reducedMotion = ref(false)
const splitElement = ref(null)
const splitSize = ref({ width: 1000, height: 80 })
const pathLengths = ref({ remediate: 400, practice: 80, advance: 400 })
const paths = computed(() => {
  const { width: w, height: h } = splitSize.value
  const x = w / 2, y = h * .45, left = w / 6, right = w * 5 / 6
  const r = Math.min(16, h * .2)
  const l = `H${left + r}Q${left} ${y} ${left} ${y + r}V${h}`
  const rr = `H${right - r}Q${right} ${y} ${right} ${y + r}V${h}`
  const trunk = `M${x} 0V${y}`, fork = `M${x} ${y}`
  return { trunk, left: fork + l, middle: fork + `V${h}`, right: fork + rr, remediate: trunk + l, practice: `M${x} 0V${h}`, advance: trunk + rr }
})
const routes = ['remediate', 'practice', 'advance']
const flowRoute = computed(() => selectedRoute.value || routes[routeIndex.value])
let frame = null
let previous = null
let elapsed = 0
let mounted = false
let motionQuery
let splitObserver
function flowStyle(route) {
  const p = phase.value
  const length = pathLengths.value[route]
  const segment = Math.min(36, length * .35)
  const travel = Math.min(p / .72, 1)
  const arrival = length / (length + segment)
  const fade = travel <= arrival ? 1 : (1 - travel) / (1 - arrival)
  const visible = props.active && !reducedMotion.value && flowRoute.value === route
  return { strokeDasharray: `${segment} ${length + segment + 10}`, strokeDashoffset: segment - (length + segment) * travel, opacity: visible ? Math.max(0, Math.min(p / .04, fade, 1)) : 0 }
}
function isFlowing(route) {
  const length = pathLengths.value[route]
  const segment = Math.min(36, length * .35)
  const halfDisappeared = .72 * (length + segment / 2) / (length + segment)
  return props.active && !reducedMotion.value && flowRoute.value === route && phase.value >= halfDisappeared && phase.value < .94
}
function tick(now) {
  if (previous !== null) elapsed += now - previous
  previous = now
  phase.value = (elapsed % 4000) / 4000
  routeIndex.value = Math.floor(elapsed / 4000) % routes.length
  frame = requestAnimationFrame(tick)
}
function syncTimeline() {
  if (frame !== null) cancelAnimationFrame(frame)
  frame = null
  previous = null
  if (mounted && props.active && !document.hidden && !reducedMotion.value) frame = requestAnimationFrame(tick)
}
function updateMotion() { reducedMotion.value = motionQuery.matches; syncTimeline() }
function selectRoute(route) { selectedRoute.value = selectedRoute.value === route ? null : route }
watch(selectedRoute, () => { elapsed = 0; phase.value = 0; routeIndex.value = 0; syncTimeline() })
watch(() => props.active, syncTimeline)
onMounted(() => {
  mounted = true
  splitObserver = new ResizeObserver(async ([entry]) => {
    splitSize.value = { width: Math.max(1, entry.contentRect.width), height: Math.max(1, entry.contentRect.height) }
    await nextTick()
    if (!mounted) return
    pathLengths.value = Object.fromEntries([...splitElement.value.querySelectorAll('.feedback-flow')].map(path => [path.dataset.route, path.getTotalLength()]))
  })
  splitObserver.observe(splitElement.value)
  motionQuery = matchMedia('(prefers-reduced-motion: reduce)')
  motionQuery.addEventListener('change', updateMotion)
  document.addEventListener('visibilitychange', syncTimeline)
  updateMotion()
})
onBeforeUnmount(() => {
  mounted = false
  syncTimeline()
  splitObserver?.disconnect()
  motionQuery?.removeEventListener('change', updateMotion)
  document.removeEventListener('visibilitychange', syncTimeline)
})
</script>
<style scoped>
.feedback-world { --route-remediate:#a54840; --route-practice:#a86720; --route-advance:#327769; }
.feedback-hero { display:block; }
.feedback-hero .feature-intro { display:grid; grid-template-columns:1.2fr 1fr; column-gap:70px; align-items:end; margin-bottom:22px; }
.feature-kicker { grid-column:1 / -1; }
.feedback-hero .feature-title { font-size:clamp(34px,3vw,48px); line-height:1.25; margin-top:14px; }
.feedback-hero .feature-intro > p { justify-self:end; margin:0 0 4px; padding-left:22px; border-left:1px solid var(--sc-line); max-width:390px; font-size:15px; line-height:1.9; }
.feedback-description > span { display:block; margin-bottom:7px; font-size:11px; letter-spacing:.12em; color:var(--sc-accent); }
.feedback-branches { height:auto; min-height:0; }
.feedback-scene-heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; color:var(--sc-muted); font-size:11px; }
.feedback-diagram { display:grid; grid-template-rows:76px 80px auto auto; }
.feedback-origin { position:relative; width:min(430px,60%); justify-self:center; padding:12px 22px; border:1px solid #c29a6466; border-radius:14px; background:var(--sc-surface); box-shadow:0 8px 30px #65451b09; }
.feedback-card-kicker { display:block; color:var(--sc-accent); font-size:10px; letter-spacing:.1em; }
.feedback-origin-content { display:flex; align-items:center; gap:12px; margin-top:6px; }
.feedback-origin-content > span:last-child { display:grid; gap:3px; }
.feedback-origin-content strong { font-size:14px; font-weight:550; }
.feedback-origin-content small { font-size:10px; color:var(--sc-muted); }
.feedback-node-letter { display:grid; place-items:center; flex:0 0 32px; height:32px; border-radius:9px; border:1px solid #b9946266; background:var(--sc-surface); color:var(--sc-accent); font:13px Consolas,monospace; }
.feedback-split { position:relative; }
.feedback-split > svg { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }
.feedback-wire { fill:none; stroke:#bda68080; stroke-width:1; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
.feedback-split marker path { fill:#bda680; }
.feedback-wire-mobile, .feedback-flow-mobile { display:none; }
.feedback-wire-joint { position:absolute; top:45%; left:50%; width:10px; height:10px; box-sizing:border-box; border:1.5px solid var(--sc-accent); border-radius:50%; background:var(--sc-surface); transform:translate(-50%,-50%); }
.feedback-flow { fill:none; stroke:var(--route-remediate); stroke-width:2.5; stroke-linecap:round; opacity:0; }
.feedback-flow-middle { stroke:var(--route-practice); }.feedback-flow-right { stroke:var(--route-advance); }
.feedback-branch-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:22px; }
.feedback-route { --branch-color:var(--route-remediate); position:relative; display:flex; flex-direction:column; min-width:0; padding:18px 22px 14px; border:1px solid var(--sc-line); border-radius:16px; background:linear-gradient(145deg,var(--sc-surface),#f5ecde80); }
.feedback-route-practice { --branch-color:var(--route-practice); }.feedback-route-advance { --branch-color:var(--route-advance); }
.feedback-route::before { content:''; position:absolute; top:-1px; left:-1px; right:-1px; height:16px; border:2px solid var(--branch-color); border-bottom:0; border-radius:16px 16px 0 0; pointer-events:none; opacity:.75; mask-image:linear-gradient(#000 0 3px,transparent 12px); }
.feedback-route-index { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border:1px solid color-mix(in srgb,var(--branch-color) 24%,transparent); border-radius:5px; background:color-mix(in srgb,var(--branch-color) 7%,var(--sc-surface)); color:var(--branch-color); font:11px system-ui,sans-serif; letter-spacing:.08em; }
.feedback-route h3 { margin:5px 0; color:var(--branch-color); font-size:20px; font-weight:550; }
.feedback-route h3 button { display:flex; width:100%; min-height:40px; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:4px; padding:0; border:0; border-radius:4px; background:transparent; color:inherit; font:inherit; text-align:left; }
.feedback-route header > p { margin:0; min-height:28px; color:var(--sc-muted); font-size:11px; line-height:1.6; }
.feedback-route-steps { position:relative; list-style:none; display:grid; grid-template-columns:1fr 1fr; gap:20px; padding:12px 0; margin:0; }
.feedback-route-steps::before { content:''; position:absolute; top:28px; left:16px; right:calc(50% - 26px); height:1px; background:var(--branch-color); opacity:.4; }
.feedback-route-steps li:first-child::after { content:''; position:absolute; top:13px; right:-10px; width:5px; height:5px; border-top:1px solid var(--branch-color); border-right:1px solid var(--branch-color); transform:rotate(45deg); }
.feedback-route-steps li { position:relative; display:flex; flex-direction:column; align-items:start; gap:8px; }
.feedback-route-steps li > span:last-child { display:grid; gap:4px; }
.feedback-route-steps .feedback-node-letter { flex-basis:auto; width:32px; color:var(--branch-color); }
.feedback-route-steps li:last-child .feedback-node-letter { box-shadow:0 0 0 3px var(--sc-surface),0 0 0 4px var(--sc-line); }
.feedback-route-steps strong { font-size:12px; font-weight:550; }
.feedback-route-steps small { font-size:10px; line-height:1.5; color:var(--sc-muted); }
.feedback-route { transition:border-color .4s ease,box-shadow .4s ease,background-color .4s ease; }
.feedback-route.is-selected { border-color:var(--branch-color); box-shadow:0 8px 30px #8f602324; background:var(--sc-surface); }
.feedback-route.is-flowing { border-color:var(--branch-color); box-shadow:0 10px 26px #8f602324; }
.feedback-route.is-selected .feedback-node-letter { border-color:var(--branch-color); }
.feedback-diagram-footer { display:flex; justify-content:space-between; gap:16px; margin-top:13px; color:var(--sc-muted); font-size:11px; }.feedback-diagram-footer small { font-size:10px; }
@media(min-width:1800px) { .feedback-hero .feature-title{font-size:54px;} .feedback-hero .feature-intro > p{font-size:19px;} .feedback-route{padding:22px 28px 18px;} .feedback-route h3{font-size:24px;} .feedback-route header > p,.feedback-route-steps strong{font-size:14px;} .feedback-route-steps small{font-size:12px;} }
@media(max-width:1100px) { .feedback-hero .feature-intro{column-gap:30px;} .feedback-hero .feature-title{font-size:36px;} .feedback-hero .feature-intro > p{font-size:14px;} .feedback-route{padding:15px;} .feedback-branch-grid{gap:12px;} .feedback-route-steps{gap:10px;} }
@media(max-width:850px) { .feedback-hero .feature-intro{grid-template-columns:1fr;gap:18px;} .feature-kicker{grid-column:auto;} .feedback-hero .feature-intro > p{font-size:16px;} .feedback-origin{width:85%;} .feedback-route-steps{grid-template-columns:1fr;} .feedback-route-steps::before{display:none;} }
@media(max-width:850px) { .feedback-hero .feature-intro > p { justify-self:start;max-width:none; } }
@media(max-width:850px) { .feedback-route-steps li:first-child::after { display:none; } }
@media(max-width:520px) { .feedback-hero .feature-title{font-size:32px;} .feedback-diagram{grid-template-rows:90px 36px auto auto;} .feedback-origin{width:100%;padding:12px;} .feedback-branch-grid{grid-template-columns:1fr;} .feedback-route-steps{grid-template-columns:1fr 1fr;} .feedback-diagram-footer{flex-direction:column;gap:5px;} .feedback-split svg,.feedback-wire-joint{display:none;} }
@media(prefers-reduced-motion:reduce) { .feedback-branches.is-active .feedback-flow,.feedback-branches.is-active .feedback-route{animation:none!important;transform:none!important;} .feedback-flow{opacity:0!important;} }
</style>
