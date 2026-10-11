<template>
  <section class="feature-world journey-world">
    <div class="feature-intro journey-heading">
      <div><div class="feature-kicker"><i />03 / ONE GRAPH. DIFFERENT STARTS.</div><h2 id="path-title" class="feature-title" tabindex="-1">同一张知识图谱，<em>不同的起点。</em></h2></div>
      <p>初始诊断确定学习阶。<br />先修关系决定下一步。</p>
    </div>
    <div class="feature-scene journey-map">
      <svg viewBox="0 0 1000 360" fill="none" aria-hidden="true" preserveAspectRatio="none">
        <defs><marker id="journey-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="4" markerHeight="4" orient="auto"><path d="M1 1L6 4L1 7" fill="none" stroke="context-stroke" stroke-width="1.5" /></marker></defs>
        <path v-for="edge in edges" :key="edge.from + edge.to" :data-from="edge.from" :data-to="edge.to" :d="edge.path" class="journey-edge" :class="{ 'is-related': edge.to === station, 'is-current': edge.tier === selected + 1 }" marker-end="url(#journey-arrow)" />
      </svg>
      <div class="route-lanes">
        <article v-for="(tier, index) in tiers" :key="tier.name" class="route-lane" :class="{ 'is-selected': selected === index, 'is-exempt': selected > index }" :data-learner="index" :style="{ '--route-color': tier.color }">
          <button type="button" class="journey-profile-select" :aria-label="'选择诊断起点：第 ' + (index + 1) + ' 阶'" :aria-pressed="selected === index" @click="chooseTier(index)"><span class="learner-avatar" aria-hidden="true">0{{ index + 1 }}</span><span><strong>{{ tier.name }}</strong><small>{{ selected === index ? '当前学习阶' : selected > index ? '定阶豁免 · 未以测评验证' : '后续学习阶' }}</small></span><span class="tier-indicator" aria-hidden="true">↓</span></button>
          <div class="journey-steps">
            <button v-for="node in nodesForTier(index + 1)" :key="node.id" class="journey-step" :class="{ 'is-prerequisite': activeNode.prerequisites.includes(node.id) }" type="button" :data-node="node.id" :data-tier="node.tier" :data-prerequisites="node.prerequisites.join(',')" :style="{ top: positions[node.id] + '%' }" :aria-label="'查看知识节点：' + node.name" :aria-pressed="station === node.id" @click="station = node.id"><i aria-hidden="true" /><span>{{ node.name }}</span><span class="node-port" aria-hidden="true" /></button>
          </div>
        </article>
      </div>
    </div>
    <div class="journey-profile" aria-live="polite"><div><span class="journey-current-label">{{ activeNode.name }} · 第 {{ activeNode.tier }} 阶</span><h3>先修：{{ prerequisiteNames || '无' }}</h3></div><p>定阶豁免不等于已掌握。<br />本阶节点完成后，才解锁下一阶。</p></div>
    <div class="feature-demo-note"><el-icon aria-hidden="true"><InfoFilled /></el-icon>项目机制示意 · 默认 RAG 图谱 · 点击阶层标题切换诊断起点</div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { projectSkillNodes } from './projectShowcaseData'
// All 13 nodes and 15 direct edges project the authoritative seed. These are not personal recommendations.
const selected = ref(0)
const station = ref('rag_basics')
const tiers = [ { name: '第 1 阶 · 零基础', color: '#6654a9', start: 'rag_basics' }, { name: '第 2 阶 · Python 基础', color: '#146d7b', start: 'chunking' }, { name: '第 3 阶 · 进阶 RAG', color: '#98602e', start: 'hybrid_retrieval' } ]
const nodesById = Object.fromEntries(projectSkillNodes.map(node => [node.id, node]))
const positions = { rag_basics: 10, document_parsing: 40, embedding: 70, chunking: 7, vector_store: 27, similarity_retrieval: 47, prompt_assembly: 67, citation: 87, hybrid_retrieval: 7, rerank: 27, hallucination_control: 47, rag_evaluation: 67, rag_tuning: 87 }
const nodesForTier = tier => projectSkillNodes.filter(node => node.tier === tier)
const activeNode = computed(() => nodesById[station.value])
const prerequisiteNames = computed(() => activeNode.value.prerequisites.map(id => nodesById[id].name).join('、'))
const edges = projectSkillNodes.flatMap(node => node.prerequisites.map(from => {
  const source = nodesById[from]
  const x1 = (source.tier - .5) * 1000 / 3, x2 = (node.tier - .5) * 1000 / 3
  const y1 = positions[from] * 3.6, y2 = positions[node.id] * 3.6
  let path
  if (source.tier !== node.tier) {
    const channel = (x1 + x2) / 2
    path = `M${x1 + 90} ${y1}C${channel} ${y1} ${channel} ${y2} ${x2 - 90} ${y2}`
  } else {
    const crossesNode = nodesForTier(node.tier).some(other => other.id !== from && other.id !== node.id && positions[other.id] > positions[from] && positions[other.id] < positions[node.id])
    if (!crossesNode) path = `M${x1} ${y1 + 22}V${y2 - 22}`
    else {
      const side = node.tier === 3 ? 1 : -1
      const port = x1 + side * 90, channel = x1 + side * (from === 'hybrid_retrieval' ? 147 : 128)
      path = `M${port} ${y1}C${channel} ${y1} ${channel} ${y2} ${port} ${y2}`
    }
  }
  return { from, to: node.id, tier: node.tier, path }
}))
function chooseTier(index) { selected.value = index; station.value = tiers[index].start }
</script>

<style scoped>
.journey-world::before { content: ''; position: absolute; z-index: -1; inset: 15% 0 0; pointer-events: none; background: radial-gradient(ellipse at 50% 60%, #35498625, transparent 65%); }
.journey-heading { display: flex; justify-content: space-between; align-items: end; gap: 24px; }.journey-heading .feature-title { font-size: clamp(34px, 3.4vw, 59px); margin-top: 16px; }.journey-heading > p { flex-shrink: 0; font-size: 16px; margin: 0 0 4px; }
.journey-map { height: 405px; margin-top: 28px; }.journey-map > svg { top: 78px; height: calc(100% - 78px); pointer-events: none; z-index: 1; }
.route-lanes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); height: 100%; }.route-lane { position: relative; min-width: 0; border-right: 1px solid #839ace1b; background: linear-gradient(180deg, #fbfcff66, transparent); }.route-lane:last-child { border: 0; }.route-lane.is-selected { background: linear-gradient(180deg, #dfe5f599, #e9edf70a); }
.journey-profile-select { position: absolute; z-index: 2; inset: 0 16px auto; width: calc(100% - 32px); display: flex; align-items: center; gap: 13px; height: 67px; padding: 8px 12px; text-align: left; border: 0 !important; border-bottom: 1px solid #839ace29 !important; border-radius: 0; background: transparent !important; }.journey-profile-select[aria-pressed="true"] { border-bottom-color: var(--route-color) !important; }.journey-profile-select:hover { border-bottom-color: var(--route-color) !important; }
.learner-avatar { color: var(--route-color); font: 23px Consolas, monospace; flex-shrink: 0; }.journey-profile-select strong { display: block; font-size: 16px; font-weight: 550; }.journey-profile-select small { display: block; margin-top: 7px; color: var(--sc-muted); font-size: 11px; line-height: 1.5; }.tier-indicator { margin-left: auto; color: var(--route-color); font-size: 21px; }
.journey-steps { position: absolute; inset: 78px 0 0; }.journey-step { position: absolute; z-index: 2; left: 50%; transform: translate(-50%, -50%); display: flex; align-items: center; justify-content: center; gap: 10px; width: 54%; min-height: 44px; padding: 8px 10px; border-radius: 5px; background: #fbfcff !important; }.journey-step > span:not(.node-port) { font-size: 15px; font-weight: 500; white-space: nowrap; }.journey-step > i { width: 5px; height: 5px; border: 1px solid var(--route-color); border-radius: 50%; flex-shrink: 0; }.node-port { position: absolute; bottom: -3px; left: calc(50% - 2px); width: 4px; height: 4px; background: #7287aa; border-radius: 50%; }.journey-step[aria-pressed="true"] { background: #e0e6f5 !important; border-color: var(--route-color) !important; box-shadow: 0 0 35px #89a6ee20; }.journey-step[aria-pressed="true"] > i { background: var(--route-color); box-shadow: 0 0 10px var(--route-color); }.journey-step.is-prerequisite { border-color: #a5b8e084; }.journey-step:hover { border-color: var(--route-color) !important; }.is-exempt .journey-step { border-style: dashed; }
.journey-edge { stroke: #7085b0; stroke-width: 1; opacity: .3; transition: opacity 450ms, stroke 450ms; }.journey-edge.is-current { opacity: .45; }.journey-edge.is-related { opacity: .95; stroke: #475bb4; stroke-width: 1.5; }.showcase-panel.is-active .journey-edge.is-related { animation: journey-reveal 1000ms var(--sc-ease) 1; }
.journey-profile { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-top: 16px; margin-top: 10px; border-top: 1px solid var(--sc-line); }.journey-current-label { color: var(--sc-accent); font-size: 15px; }.journey-profile h3 { margin: 7px 0 0; font-size: 14px; font-weight: 400; color: var(--sc-ink); }.journey-profile p { margin: 0; color: var(--sc-muted); font-size: 12px; line-height: 1.7; }.journey-world .feature-demo-note { margin-top: 12px; }
@keyframes journey-reveal { from { opacity: .3; } to { opacity: .95; } }
@media (min-width: 1800px) { .journey-heading .feature-title { font-size: 65px; }.journey-heading > p { font-size: 20px; }.journey-map { height: 520px; margin-top: 36px; }.journey-map > svg { top: 90px; height: calc(100% - 90px); }.journey-steps { top: 90px; }.journey-profile-select { height: 76px; inset-inline: 24px; width: calc(100% - 48px); gap: 23px; }.learner-avatar { font-size: 30px; }.journey-profile-select strong { font-size: 22px; }.journey-profile-select small { font-size: 14px; }.journey-step { min-height: 54px; }.journey-step > span:not(.node-port) { font-size: 20px; }.journey-step > i { width: 7px; height: 7px; }.journey-current-label { font-size: 19px; }.journey-profile h3 { font-size: 18px; }.journey-profile p { font-size: 14px; } }
@media (max-width: 1100px) { .journey-map { height: 345px; margin-top: 23px; }.journey-map > svg { top: 67px; height: calc(100% - 67px); }.journey-steps { top: 67px; }.journey-profile-select { inset-inline: 10px; width: calc(100% - 20px); padding-inline: 7px; height: 57px; gap: 10px; }.journey-profile-select strong { font-size: 14px; }.journey-profile-select small { font-size: 10px; }.journey-step { padding-inline: 6px; gap: 6px; }.journey-step > span:not(.node-port) { font-size: 13px; }.journey-heading > p { display: none; }.journey-world .feature-demo-note { font-size: 11px; } }
@media (max-width: 850px) { .journey-heading { flex-direction: column; align-items: start; gap: 15px; }.journey-heading > p { display: block; font-size: 17px; }.journey-map { height: auto; }.journey-map > svg { display: none; }.route-lanes { grid-template-columns: 1fr; gap: 20px; }.route-lane { padding: 20px; border: 1px solid var(--sc-line); border-radius: 7px; background: #fbfcff; }.route-lane:last-child { border: 1px solid var(--sc-line); }.route-lane.is-selected { border-color: var(--route-color); }.journey-profile-select { position: static; width: 100%; min-height: 62px; height: auto; padding: 0 0 15px; }.journey-profile-select strong { font-size: 18px; }.journey-profile-select small { font-size: 12px; }.journey-steps { position: static; display: flex; flex-direction: column; align-items: center; gap: 16px; margin-top: 22px; padding-left: 16px; border-left: 1px solid #8ca7de35; }.journey-step { position: relative; inset: auto !important; transform: none; width: 100%; min-height: 50px; justify-content: start; padding-inline: 14px; }.journey-step > span:not(.node-port) { font-size: 16px; }.node-port { display: none; }.journey-profile { flex-wrap: wrap; align-items: start; }.journey-profile > div { min-width: 0; }.journey-profile h3 { line-height: 1.7; }.journey-profile p { font-size: 13px; } }
@media (max-width: 520px) { .journey-heading .feature-title { font-size: 34px; }.route-lane { padding: 16px; }.journey-profile h3 { font-size: 14px; } }
</style>
