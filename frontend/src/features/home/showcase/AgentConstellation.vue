<template>
  <section class="feature-world agent-world">
    <div class="feature-hero">
      <div class="feature-intro">
        <div class="feature-kicker"><i />01 / MULTI-AGENT</div>
        <h2 id="agents-title" class="feature-title" tabindex="-1">多位 Agent，<br /><em>一套协作工作流。</em></h2>
        <p>诊断、规划、生成与审核各司其职。<br />画像和检索证据，在工作流中传递。</p>
        <div class="agent-demo-controls">
          <button class="feature-button" type="button" @click="play"><el-icon aria-hidden="true"><VideoPlay /></el-icon>{{ paused ? '继续演示' : '演示一次协作' }}</button>
          <button v-if="running" class="feature-button secondary" type="button" @click="pause">暂停演示</button>
        </div>
        <div class="feature-demo-note"><el-icon aria-hidden="true"><InfoFilled /></el-icon>项目机制示意 · 含可选 Claim 分支</div>
        <div class="agent-role-panel" data-role-panel aria-live="polite">
          <h3>{{ activeRole.title }} Agent</h3>
          <p>{{ activeRole.detail }}</p>
          <div class="agent-io"><span>IN <b>{{ activeRole.input }}</b></span><span>OUT <b>{{ activeRole.output }}</b></span></div>
        </div>
      </div>
      <div class="feature-scene agent-constellation" :class="{ 'is-running': running, 'is-complete': complete }">
        <div class="agent-nebula" aria-hidden="true" />
        <div class="agent-stage">
        <svg viewBox="0 0 700 700" fill="none" aria-hidden="true">
          <defs>
            <radialGradient id="agent-field"><stop stop-color="#8254bc" stop-opacity=".17" /><stop offset="1" stop-color="#8254bc" stop-opacity="0" /></radialGradient>
            <linearGradient v-for="(role, index) in roles" :id="'agent-beam-' + index" :key="role.code" gradientUnits="userSpaceOnUse" x1="350" y1="350" :x2="role.endX" :y2="role.endY"><stop stop-color="#8150b3" stop-opacity=".15" /><stop offset=".5" stop-color="#7541a8" /><stop offset="1" stop-color="#7164b8" stop-opacity=".25" /></linearGradient>
          </defs>
          <circle cx="350" cy="350" r="280" fill="url(#agent-field)" />
          <g class="agent-starfield">
            <circle v-for="star in stars" :key="star.x" :cx="star.x" :cy="star.y" :r="star.size" fill="#947ab3" :opacity="star.opacity" />
          </g>
          <g stroke="#8b6caf" stroke-opacity=".13">
            <circle cx="350" cy="350" r="280" />
            <circle cx="350" cy="350" r="225" stroke-dasharray="2 12" />
            <circle cx="350" cy="350" r="165" />
          </g>
          <g class="agent-spokes">
            <path v-for="(role, index) in roles" :key="role.code" :d="role.path" :class="{ 'is-active': selected === index }" class="agent-connection" :stroke="'url(#agent-beam-' + index + ')'" />
          </g>
        </svg>
        <div class="agent-core" aria-hidden="true">
          <div class="agent-core-ring" />
          <span class="agent-core-glyph"><el-icon><Connection /></el-icon></span>
          <small>SHARED STATE</small><strong>工作流上下文</strong><span class="agent-core-context">画像 · 证据 · 资源</span>
        </div>
        <button v-for="(role, index) in roles" :key="role.code" type="button" class="agent-role" :style="{ '--agent-x': role.unitX, '--agent-y': role.unitY }" :aria-label="'查看' + role.title + '智能体'" :aria-pressed="selected === index" @click="chooseRole(index)">
          <span class="agent-role-icon" aria-hidden="true"><svg viewBox="0 0 40 40" fill="none"><path d="M20 5v5M15 4h10M9 15a5 5 0 0 1 5-5h12a5 5 0 0 1 5 5v13a5 5 0 0 1-5 5H14a5 5 0 0 1-5-5V15Z" stroke="currentColor" stroke-width="1.5"/><path d="M4 19v7M36 19v7M16 27h8" stroke="currentColor" stroke-width="1.5"/><circle cx="15" cy="20" r="2" fill="currentColor"/><circle cx="25" cy="20" r="2" fill="currentColor"/></svg></span>
          <span class="agent-role-copy"><small>{{ role.code }}</small><strong>{{ role.title }}<span v-if="role.optional"> · 可选</span></strong></span>
          <i aria-hidden="true" />
        </button>
        </div>
        <div class="agent-transmission"><span class="agent-status-dot" aria-hidden="true" /><span role="status" aria-live="polite">{{ status }}</span></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Connection, VideoPlay, InfoFilled } from '@element-plus/icons-vue'

const roles = [
  { code: 'DIAGNOSIS AGENT', title: '诊断', detail: '读取学习者画像，分析当前薄弱点；随后检索节点提供证据，门禁通过后进入规划。', input: '学习者画像', output: '诊断摘要' },
  { code: 'PLANNER AGENT', title: '规划', detail: '结合画像、目标节点与检索证据，制定本轮资源计划。', input: '画像 + 证据', output: '资源计划' },
  { code: 'RESOURCE AGENTS', title: '生成', detail: '按资源类型分派讲义、实操、测试题、复习清单或案例的专用 Agent。', input: '资源规格', output: '学习资源' },
  { code: 'REVIEWER AGENT', title: '审核', detail: '检查资源质量与证据使用，返回审核决定。', input: '资源 + 证据', output: '审核决定' },
  { code: 'CLAIM AGENTS', title: 'Claim', optional: true, detail: '开启 Claim 审核后，从资源抽取陈述，再由独立判定环节对照 Evidence；结果交给确定性规则处理。', input: '陈述 + 证据', output: '逐条判定' },
].map((role, index) => {
  const angle = (-162 + index * 72) * Math.PI / 180
  const unitX = Math.cos(angle)
  const unitY = Math.sin(angle)
  // A single radial rule keeps all five spokes and node positions symmetrical.
  const endX = 350 + unitX * 280
  const endY = 350 + unitY * 280
  return { ...role, unitX, unitY, endX, endY, path: `M350 350 Q${(350 + endX) / 2} ${(350 + endY) / 2} ${endX} ${endY}` }
})
const props = defineProps({ active: { type: Boolean, default: true } })
const stars = Array.from({ length: 86 }, (_, i) => ({ x: 24 + (i * 137 % 652), y: 30 + (i * 97 % 640), size: i % 7 ? .7 : 1.7, opacity: .15 + (i % 5) * .12 }))
const selected = ref(0)
const running = ref(false)
const paused = ref(false)
const complete = ref(false)
const roleDuration = 1800
let timer
const activeRole = computed(() => roles[selected.value])
const status = computed(() => complete.value ? '协作示意完成 · Claim 为可选分支' : running.value ? roles[selected.value].title + ' Agent · 流程示意' : paused.value ? '演示已暂停' : '点击 Agent，查看输入与输出')
function clearTimer() { window.clearTimeout(timer) }
function advance() {
  if (selected.value === roles.length - 1) { running.value = false; complete.value = true; return }
  selected.value++
  timer = window.setTimeout(advance, roleDuration)
}
function play() {
  clearTimer()
  if (!paused.value) selected.value = 0
  paused.value = false
  complete.value = false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { selected.value = 4; complete.value = true; running.value = false; return }
  running.value = true
  timer = window.setTimeout(advance, roleDuration)
}
function pause() { clearTimer(); running.value = false; paused.value = true }
function chooseRole(index) { clearTimer(); running.value = false; paused.value = false; complete.value = false; selected.value = index }
watch(() => props.active, active => { if (!active && running.value) pause() })
onBeforeUnmount(clearTimer)
</script>

<style scoped>
.agent-world::before { content: ''; position: absolute; z-index: -1; right: -16%; top: -6%; bottom: 0; width: 85%; background: radial-gradient(ellipse, #7744b91e, transparent 68%); pointer-events: none; }
.agent-demo-controls { display: flex; flex-wrap: wrap; gap: 10px; }.agent-demo-controls .secondary { margin-left: 0; }
.agent-role-panel { padding-left: 18px; margin-top: 36px; border-left: 1px solid #b59ae563; max-width: 410px; }
.agent-role-panel h3 { margin: 0; font-size: 19px; font-weight: 500; }.agent-role-panel p { margin: 12px 0 0; color: var(--sc-muted); font-size: 15px; line-height: 1.8; }
.agent-io { display: flex; gap: 20px; margin-top: 16px; color: var(--sc-accent); font: 11px Consolas, monospace; }.agent-io span { display: grid; gap: 7px; }.agent-io b { font: 14px system-ui, sans-serif; color: var(--sc-ink); }
.agent-core-context { margin-top: 12px; color: var(--sc-muted); font-size: 12px; }
.agent-role-copy { min-width: 0; }.agent-role-copy small { display: block; margin-bottom: 8px; color: var(--sc-accent); font: 10px Consolas, monospace; white-space: nowrap; }.agent-role-copy strong > span { font-size: 12px; }
.agent-role-icon > svg { position: static; width: 36px; height: 36px; pointer-events: none; }
.agent-constellation { perspective: 1000px; container-type: size; height: clamp(540px, 65dvh, 740px); }
.agent-stage { --agent-radius: 40%; position: absolute; left: 50%; top: 50%; width: min(100%, 100cqh); aspect-ratio: 1; transform: translate(-50%, -50%); }
.agent-spokes { transform-origin: 350px 350px; }
.agent-nebula { position: absolute; inset: 11% 3% 10%; background: radial-gradient(ellipse at 49% 48%, #9c63fb18, transparent 60%); border-radius: 50%; }
.agent-connection { stroke-width: 1; opacity: .38; transition: opacity 700ms ease, stroke-width 700ms ease; }.agent-connection.is-active { opacity: 1; stroke-width: 2.2; filter: drop-shadow(0 0 4px #b490ff70); }
.agent-constellation.is-running .agent-connection.is-active { stroke-dasharray: 7 14; animation: agent-data 1.5s linear 1; }
.agent-core { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); display: flex; align-items: center; justify-content: center; flex-direction: column; width: 190px; height: 190px; border: 1px solid #b895fd73; border-radius: 50%; background: radial-gradient(ellipse at 35% 20%, #f7efff, #e6d9f3 65%); box-shadow: inset 0 1px 20px #d2aaff16, 0 0 85px #9b60ff1b; }
.agent-core-ring { position: absolute; inset: -11px; border: 1px solid #b18fe330; border-radius: 50%; }.agent-core-ring::after { content: ''; position: absolute; inset: -9px; border: 1px dashed #b18fe31a; border-radius: 50%; }
.agent-core-glyph { display: grid; place-items: center; font-size: 33px; width: 49px; height: 49px; color: #7541a8; margin-bottom: 9px; }
.agent-core small { font: 9px Consolas, monospace; color: #6d5c7e; }.agent-core strong { margin-top: 12px; font-size: 19px; font-weight: 550; }
.agent-role { position: absolute; left: calc(50% + var(--agent-x) * var(--agent-radius)); top: calc(50% + var(--agent-y) * var(--agent-radius)); transform: translate(-50%, -50%); display: flex; align-items: center; gap: 12px; width: 160px; min-height: 76px; padding: 15px 13px; border-radius: 13px; box-shadow: 0 14px 36px #51336b0e; text-align: left; }
.agent-constellation .agent-role { background: #fdfbff; border-color: #8a68af33; color: #52405f; transition: transform 350ms var(--sc-ease), background-color 700ms var(--sc-ease), border-color 700ms ease, color 700ms ease, box-shadow 700ms ease; }
.agent-role:hover { transform: translate(-50%, calc(-50% - 4px)); }.agent-constellation .agent-role[aria-pressed="true"] { background: #eadcf8; border-color: #7541a8; color: #44215d; box-shadow: 0 0 0 1px #7541a824, 0 12px 44px #7541a81c, inset 0 1px 0 #ffffffb3; }
.agent-role .agent-role-copy small { color: #6d5c7e; transition: color 700ms ease; }.agent-role[aria-pressed="true"] .agent-role-copy small { color: #633790; }
.agent-role .agent-role-icon { color: #816398; transition: color 700ms ease; }.agent-role[aria-pressed="true"] .agent-role-icon { color: #7541a8; }
.agent-role-icon { display: grid; place-items: center; width: 31px; height: 35px; color: #7541a8; font-size: 25px; flex-shrink: 0; }
.agent-role strong { display: block; font-size: 18px; font-weight: 500; white-space: nowrap; }
.agent-role > i { position: absolute; top: 12px; right: 12px; width: 5px; height: 5px; border-radius: 50%; background: #786888; transition: background-color 700ms ease, box-shadow 700ms ease; }.agent-role[aria-pressed="true"] > i { background: #7541a8; box-shadow: 0 0 0 4px #7541a81c, 0 0 12px #9c78c4; }
.agent-transmission { position: absolute; bottom: 6px; left: 5%; right: 5%; display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 42px; color: var(--sc-muted); font-size: 12px; }
.agent-status-dot { width: 5px; height: 5px; border-radius: 50%; background: #7541a8; flex-shrink: 0; }
@keyframes agent-data { from { stroke-dashoffset: 63; } to { stroke-dashoffset: 0; } }
@media (min-width: 1800px) { .agent-core { width: 226px; height: 226px; }.agent-core strong { font-size: 25px; }.agent-core small { font-size: 11px; }.agent-role { width: 210px; min-height: 94px; padding: 24px; }.agent-role strong { font-size: 22px; }.agent-role-panel p { font-size: 17px; }.agent-role-panel h3 { font-size: 22px; }.agent-transmission { font-size: 14px; } }
@media (max-height: 820px) and (min-width: 1101px) { .agent-core { width: 170px; height: 170px; } }
@media (max-width: 1100px) { .agent-core { width: 150px; height: 150px; }.agent-core strong { font-size: 16px; }.agent-core-glyph { font-size: 28px; height: 34px; width: 34px; }.agent-core small { font-size: 8px; }.agent-role { width: 160px; min-height: 72px; gap: 10px; padding: 15px 12px; }.agent-role strong { font-size: 17px; }.agent-role-icon { width: 25px; font-size: 23px; } }
@media (max-width: 850px) { .agent-constellation { height: 550px; } }
@media (max-width: 520px) { .agent-constellation { height: 470px; }.agent-stage { --agent-radius: 34%; }.agent-spokes { transform: scale(.85); }.agent-role-panel { max-width: none; }.agent-core { width: 100px; height: 100px; }.agent-core strong { font-size: 12px; margin-top: 7px; }.agent-core small { font-size: 8px; }.agent-core-glyph { font-size: 25px; margin-bottom: 6px; height: 30px; }.agent-role { width: 112px; min-height: 72px; gap: 6px; padding: 9px; }.agent-role-icon { width: 21px; font-size: 21px; }.agent-role-icon > svg { width: 24px; height: 24px; }.agent-role-copy small { font-size: 8px; margin-bottom: 5px; }.agent-core-context { font-size: 9px; margin-top: 7px; }.agent-role strong { font-size: 15px; }.agent-role-copy strong > span { font-size: 10px; }.agent-role > i { top: 8px; right: 8px; }.agent-transmission { left: 0; right: 0; font-size: 12px; } }
</style>
