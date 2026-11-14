<template>
  <div ref="frame" class="candidate-map" :class="{ 'has-edges': edges.length }">
    <div class="candidate-edges" aria-hidden="true">
      <span v-for="segment in connections" :key="segment.key" :class="{ 'is-end': segment.end }" :style="segment.style"></span>
    </div>
    <el-radio-group v-model="selected" class="candidate-tiers" :aria-label="label" :disabled="disabled">
      <div v-for="[tier, nodes] in tiers" :key="tier" class="candidate-tier">
        <span class="candidate-tier-label">第 {{ tier }} 阶</span>
        <div class="candidate-nodes">
          <el-radio v-for="node in nodes" :key="node.skill_node_id" :label="node.skill_node_id"
            :data-node-id="node.skill_node_id" class="candidate-node">
            {{ node.name }}
            <small v-if="node.reason_codes?.includes('INITIAL_DIAGNOSTIC_PASSED')">可选择</small>
            <small v-else-if="node.reason_codes?.includes('PREVIOUSLY_MASTERED_REVIEW')">已掌握 · 可复习</small>
          </el-radio>
        </div>
      </div>
    </el-radio-group>
    <p v-if="connections.length" class="candidate-map-legend">箭头指向依赖该前置能力的节点。</p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const selected = defineModel({ type: String, required: true })
const props = defineProps({
  nodes: { type: Array, required: true },
  label: { type: String, required: true },
  disabled: Boolean,
})
const frame = ref(null)
const connections = ref([])
const tiers = computed(() => {
  const groups = new Map()
  for (const node of props.nodes) {
    if (!groups.has(node.tier)) groups.set(node.tier, [])
    groups.get(node.tier).push(node)
  }
  return [...groups.entries()].sort(([left], [right]) => left - right)
})
const edges = computed(() => {
  const visible = new Set(props.nodes.map(node => node.skill_node_id))
  return props.nodes.flatMap(node => [...new Set(node.prerequisite_ids || [])]
    .filter(id => id !== node.skill_node_id && visible.has(id))
    .map(id => ({ source: id, target: node.skill_node_id })))
})

function lineSegments(from, to, origin, edgeKey) {
  const y1 = from.top + from.height / 2
  const y2 = to.top + to.height / 2
  const sharesColumn = from.left < to.right && to.left < from.right
  const rail = Math.max(from.right, to.right) + 12
  const points = sharesColumn
    ? [[from.right + 3, y1], [rail, y1], [rail, y2], [to.right + 3, y2]]
    : from.right < to.left
      ? [[from.right + 3, y1], [to.left - 3, y2]]
      : [[from.left - 3, y1], [to.right + 3, y2]]
  return points.slice(1).map(([x2, endY], index) => {
    const [x1, startY] = points[index]
    return {
      key: `${edgeKey}:${index}`, end: index === points.length - 2,
      style: {
        left: `${x1 - origin.left}px`,
        top: `${startY - origin.top}px`,
        width: `${Math.hypot(x2 - x1, endY - startY)}px`,
        transform: `rotate(${Math.atan2(endY - startY, x2 - x1)}rad)`,
      },
    }
  })
}

watch([frame, edges], ([container, links], _previous, onCleanup) => {
  connections.value = []
  if (!container || !links.length) return
  const elements = [...container.querySelectorAll('[data-node-id]')]
  function measure() {
    const origin = container.getBoundingClientRect()
    const boxes = new Map(elements.map(element => [element.dataset.nodeId, element.getBoundingClientRect()]))
    connections.value = links.flatMap(({ source, target }) => {
      const from = boxes.get(source)
      const to = boxes.get(target)
      return from && to ? lineSegments(from, to, origin, JSON.stringify([source, target])) : []
    })
  }
  measure()
  const observer = new ResizeObserver(measure)
  observer.observe(container)
  elements.forEach(element => observer.observe(element))
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
</script>

<style scoped>
.candidate-map {
  position: relative;
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid #bbd7e5;
  border-radius: 11px;
  background: radial-gradient(circle, #b9d5e2 1px, transparent 1.2px) 0 0 / 16px 16px, #eaf5fa;
}
.candidate-tiers { position: relative; display: flex; width: 100%; flex-wrap: wrap; align-items: flex-start; gap: 18px 26px; }
.candidate-tier { display: grid; min-width: 0; flex: 1 1 190px; gap: 10px; }
.candidate-tier-label {
  justify-self: start;
  padding: 2px 7px;
  border: 1px solid #cfdfeb;
  border-radius: 5px;
  background: #f9fcfe;
  color: #3a5a72;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.5;
}
.candidate-nodes { display: flex; min-width: 0; flex-wrap: wrap; gap: 12px 16px; }
.has-edges .candidate-nodes { display: grid; justify-items: start; padding-inline-end: 16px; }
.candidate-map .candidate-node {
  flex: 0 1 180px;
  min-width: 0;
  min-height: 48px;
  height: auto;
  margin: 0;
  padding: 9px 12px;
  border: 1px solid #a8c5d9;
  border-radius: 8px;
  background: #fff;
  color: #1f4661;
}
.candidate-map .candidate-node:hover { border-color: #5184a5; }
.candidate-map .candidate-node.is-checked {
  border-color: #3c837b;
  background: #e4f4f0;
  color: #174d47;
  box-shadow: inset 0 -2px #63a69b;
}
.candidate-map.has-edges .candidate-node { width: min(100%, 180px); }
.candidate-map .candidate-node:has(input:focus-visible) { outline: 2px solid #236a89; outline-offset: 2px; }
.candidate-map :deep(.el-radio__label) { min-width: 0; color: inherit; font-size: 13px; font-weight: 600; line-height: 1.45; white-space: normal; overflow-wrap: anywhere; }
.candidate-edges { position: absolute; inset: 0; pointer-events: none; }
.candidate-edges span { position: absolute; border-top: 1px solid #54819a; transform-origin: left center; }
.candidate-edges .is-end::after { position: absolute; top: -3px; right: 0; width: 5px; height: 5px; border-top: 1px solid #54819a; border-right: 1px solid #54819a; transform: rotate(45deg); content: ''; }
.candidate-map-legend { position: relative; margin: 10px 0 0; color: #3a5a72; font-size: 12px; line-height: 1.5; }
@media (max-width: 760px) {
  .candidate-tier { flex-basis: 100%; }
  .candidate-map .candidate-node { flex: 1 1 120px; }
}
</style>
