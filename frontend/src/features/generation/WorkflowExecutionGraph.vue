<template>
  <section class="execution-graph" aria-label="工作流执行链路">
    <p class="execution-graph-accessible-description">
      最新有编号记录在上，箭头从旧步骤指向新步骤。返工和复审独立显示，关键节点可查看详情；无编号记录置后，执行顺序未记录。
    </p>

    <div v-if="!displayNodes.length" class="execution-graph-empty">
      <span class="execution-graph-waiting-orbit" aria-hidden="true"><span></span></span>
      <span>等待执行记录</span>
    </div>

    <div v-else ref="planeElement" class="execution-graph-plane">
      <svg
        v-if="geometry.width && geometry.height"
        class="execution-graph-connections"
        :viewBox="`0 0 ${geometry.width} ${geometry.height}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <g
          v-for="edge in geometry.edges"
          :key="edge.key"
          class="execution-graph-connection"
          :class="[`tone-${edge.tone}`, { 'is-active': edge.active }]"
        >
          <path class="execution-graph-edge-halo" :d="edge.path" />
          <path
            class="execution-graph-edge"
            :d="edge.path"
            :data-from-step="edge.from"
            :data-to-step="edge.to"
          />
          <path v-if="edge.directed" class="execution-graph-edge-arrow" d="M-4-3 0 0-4 3" :transform="edge.arrowTransform" />
        </g>
      </svg>

      <ol class="execution-graph-nodes">
        <li
          v-for="entry in displayNodes"
          :key="entry.key"
          class="execution-graph-entry"
          :class="{ 'is-track-offset': entry.flowIndex % 2 === 1, 'is-auxiliary': !entry.meta.inspectable }"
        >
          <component
            :is="entry.meta.inspectable ? 'button' : 'div'"
            :ref="element => setRowElement(element, entry.key)"
            :type="entry.meta.inspectable ? 'button' : undefined"
            class="execution-graph-node"
            :class="[
              `status-${statusTone(entry.step.status)}`,
              {
                'is-inspectable': entry.meta.inspectable,
                'is-selected': selectedKey === entry.recordKey,
                'is-revision': isRevision(entry),
                'is-terminal': entry.meta.key === 'finalize',
              },
            ]"
            :data-step-id="entry.recordKey"
            :data-record-key="entry.key"
            :data-node-key="entry.meta.key"
            :data-inspectable="entry.meta.inspectable"
            :aria-label="entry.meta.inspectable ? nodeLabel(entry) : undefined"
            :aria-pressed="entry.meta.inspectable ? selectedKey === entry.recordKey : undefined"
            v-on="entry.meta.inspectable ? { click: () => inspectStep(entry) } : {}"
          >
            <span
              :ref="element => setAnchorElement(element, entry.key)"
              class="execution-graph-anchor"
              aria-hidden="true"
            >
              <svg class="execution-graph-emblem" viewBox="0 0 60 60" fill="none">
                <template v-if="entry.meta.key === 'finalize'">
                  <circle class="execution-graph-orbit execution-graph-terminal-orbit" cx="30" cy="30" r="28" />
                  <circle class="execution-graph-terminal-core" cx="30" cy="30" r="22" />
                </template>
                <template v-else>
                  <path class="execution-graph-orbit" d="M30 1 55.11 15.5V44.5L30 59 4.89 44.5V15.5Z" />
                  <path class="execution-graph-hexagon" d="M30 5 51.65 17.5V42.5L30 55 8.35 42.5V17.5Z" />
                  <path class="execution-graph-facet" d="M30 10 47.32 20V40L30 50 12.68 40V20Z" />
                  <circle class="execution-graph-port" cx="30" cy="5" r="2" />
                  <circle class="execution-graph-port" cx="30" cy="55" r="2" />
                </template>
                <g class="execution-graph-symbol" transform="translate(18 18)">
                  <path v-for="(path, pathIndex) in iconPaths(entry.meta.key)" :key="pathIndex" :d="path" />
                </g>
              </svg>
            </span>

            <span class="execution-graph-node-content">
              <span class="execution-graph-node-eyebrow">
                <span class="execution-graph-sequence">{{ sequenceLabel(entry) }}</span>
                <span v-if="entry.totalCalls > 1" class="execution-graph-call-count">第 {{ entry.callIndex }} 次调用</span>
                <span v-if="isRevision(entry)" class="execution-graph-revision-label">返工</span>
              </span>
              <span class="execution-graph-node-main">
                <strong class="execution-graph-node-title">{{ entry.meta.title }}</strong>
                <span class="execution-graph-status">
                  <span class="execution-graph-status-dot" aria-hidden="true"></span>
                  {{ statusLabel(entry.step.status) }}
                </span>
              </span>
              <span class="execution-graph-node-footer execution-graph-node-secondary">
                <span class="execution-graph-action">{{ actionLabel(entry) }}</span>
                <span v-if="hasDuration(entry.step)" class="execution-graph-duration">{{ formatDuration(entry.step.duration_ms) }}</span>
                <svg v-if="entry.meta.inspectable" class="execution-graph-inspect" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M3 7h8M8 4l3 3-3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
            </span>
          </component>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { canInspectStep, formatDuration, workflowNodeMeta } from './workflowPresentation'
import { iconPaths } from './workflowNodeIcons.js'

const props = defineProps({ trace: { type: Array, default: () => [] } })
const emit = defineEmits(['inspect-step'])
const selectedKey = ref(null)
const planeElement = ref(null)
const geometry = ref({ width: 0, height: 0, edges: [] })
const anchorElements = new Map()
const rowElements = new Map()
let resizeObserver
let measurementFrame = 0
let disposed = false
let scrollRestoreVersion = 0

function recordedSequence(step) {
  for (const value of [step.sequence, step.step_sequence]) {
    if (value == null || value === '') continue
    const sequence = Number(value)
    if (Number.isInteger(sequence) && sequence > 0) return sequence
  }
  return null
}

const orderedTrace = computed(() => props.trace
  .filter(step => step && typeof step === 'object')
  .map((step, index) => ({
    step,
    meta: workflowNodeMeta(step),
    recordKey: step.step_id || step.key || `record:${index}`,
    originalIndex: index,
    sequence: recordedSequence(step),
  }))
  .sort((left, right) => {
    if (left.sequence == null && right.sequence != null) return 1
    if (right.sequence == null && left.sequence != null) return -1
    return (left.sequence ?? 0) - (right.sequence ?? 0) || left.originalIndex - right.originalIndex
  }))

const chronologicalNodes = computed(() => {
  const totals = new Map()
  const calls = new Map()
  const identities = new Map()
  const callKey = record => record.step.node_name || record.step.agent_name ? record.meta.key : record.recordKey
  for (const record of orderedTrace.value) {
    const key = callKey(record)
    totals.set(key, (totals.get(key) || 0) + 1)
  }
  return orderedTrace.value.map((record, flowIndex) => {
    const key = callKey(record)
    const callIndex = (calls.get(key) || 0) + 1
    const duplicateIndex = identities.get(record.recordKey) || 0
    calls.set(key, callIndex)
    identities.set(record.recordKey, duplicateIndex + 1)
    return {
      ...record,
      key: `${record.recordKey}:${duplicateIndex}`,
      flowIndex,
      callIndex,
      totalCalls: totals.get(key),
    }
  })
})

const displayNodes = computed(() => [...chronologicalNodes.value].sort((left, right) => {
  if (left.sequence == null && right.sequence != null) return 1
  if (right.sequence == null && left.sequence != null) return -1
  return (right.sequence ?? 0) - (left.sequence ?? 0) || left.originalIndex - right.originalIndex
}))
const displayOrder = computed(() => JSON.stringify(displayNodes.value.map(entry => entry.key)))

watch(orderedTrace, records => {
  if (!records.some(record => record.recordKey === selectedKey.value)) selectedKey.value = null
})
watch(displayOrder, async () => {
  // Capture before Vue patches the DOM. A status-only update keeps the same
  // membership and order, so it never writes to the reading position.
  const plane = planeElement.value
  const scroller = plane?.closest('.process-scroll')
  if (!scroller) return
  const restoreVersion = ++scrollRestoreVersion
  const viewport = scroller.getBoundingClientRect()
  const viewportTop = viewport.top + scroller.clientTop
  const viewportBottom = viewportTop + scroller.clientHeight
  const firstVisible = [...plane.querySelectorAll('.execution-graph-node')].find(element => {
    const bounds = element.getBoundingClientRect()
    return bounds.bottom > viewportTop && bounds.top < viewportBottom
  })
  const checkpoint = {
    atTop: scroller.scrollTop <= 24,
    scrollTop: scroller.scrollTop,
    key: firstVisible?.dataset.recordKey,
    offset: firstVisible ? firstVisible.getBoundingClientRect().top - viewportTop : null,
  }
  await nextTick()
  if (disposed || restoreVersion !== scrollRestoreVersion || !scroller.isConnected
    || planeElement.value?.closest('.process-scroll') !== scroller) return
  if (checkpoint.atTop) scroller.scrollTop = 0
  else {
    const anchor = rowElements.get(checkpoint.key)
    if (anchor && checkpoint.offset != null) {
      const nextViewportTop = scroller.getBoundingClientRect().top + scroller.clientTop
      scroller.scrollTop += anchor.getBoundingClientRect().top - nextViewportTop - checkpoint.offset
    } else scroller.scrollTop = checkpoint.scrollTop
  }
}, { flush: 'pre' })
watch(displayNodes, () => nextTick(scheduleMeasurement), { flush: 'post' })
watch(planeElement, (element, previous) => {
  if (previous) resizeObserver?.unobserve(previous)
  if (element) resizeObserver?.observe(element)
  scheduleMeasurement()
})

function setAnchorElement(element, key) {
  if (element) anchorElements.set(key, element)
  else anchorElements.delete(key)
  scheduleMeasurement()
}

function setRowElement(element, key) {
  const previous = rowElements.get(key)
  if (previous === element) return
  if (previous) resizeObserver?.unobserve(previous)
  if (element) {
    rowElements.set(key, element)
    resizeObserver?.observe(element)
  } else rowElements.delete(key)
  scheduleMeasurement()
}

function scheduleMeasurement() {
  if (disposed || measurementFrame) return
  measurementFrame = requestAnimationFrame(measureConnections)
}

function measureConnections() {
  measurementFrame = 0
  const plane = planeElement.value
  if (!plane) {
    if (geometry.value.width) geometry.value = { width: 0, height: 0, edges: [] }
    return
  }
  // Read every anchor before updating SVG geometry. Connections express only
  // recorded sequence, never inferred parallel branches or dependencies.
  const bounds = plane.getBoundingClientRect()
  const anchors = displayNodes.value.map(entry => {
    const rect = anchorElements.get(entry.key)?.getBoundingClientRect()
    return rect ? {
      entry,
      x: rect.left - bounds.left + rect.width / 2,
      y: rect.top - bounds.top + rect.height / 2,
    } : null
  })
  const edges = []
  for (let index = 0; index < anchors.length - 1; index += 1) {
    const from = anchors[index + 1]
    const to = anchors[index]
    if (!from || !to) continue
    const middleY = (from.y + to.y) / 2
    const arrowAngle = Math.atan2((to.y - from.y) * 0.75, (to.x - from.x) * 1.5) * 180 / Math.PI
    edges.push({
      key: `${from.entry.key}>${to.entry.key}`,
      from: from.entry.recordKey,
      to: to.entry.recordKey,
      path: `M ${from.x} ${from.y} C ${from.x} ${middleY}, ${to.x} ${middleY}, ${to.x} ${to.y}`,
      arrowTransform: `translate(${(from.x + to.x) / 2} ${middleY}) rotate(${arrowAngle})`,
      directed: from.entry.sequence != null && to.entry.sequence != null && from.entry.sequence < to.entry.sequence,
      tone: isRevision(to.entry) ? 'warning' : statusTone(to.entry.step.status),
      active: to.entry.step.status === 'running',
    })
  }
  const measured = { width: bounds.width, height: bounds.height, edges }
  if (JSON.stringify(measured) !== JSON.stringify(geometry.value)) geometry.value = measured
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(scheduleMeasurement)
    if (planeElement.value) resizeObserver.observe(planeElement.value)
    for (const element of rowElements.values()) resizeObserver.observe(element)
  }
  window.addEventListener('resize', scheduleMeasurement)
  scheduleMeasurement()
})

onBeforeUnmount(() => {
  disposed = true
  scrollRestoreVersion += 1
  if (measurementFrame) cancelAnimationFrame(measurementFrame)
  resizeObserver?.disconnect()
  window.removeEventListener('resize', scheduleMeasurement)
})

function inspectStep(entry) {
  if (!canInspectStep(entry.step)) return
  selectedKey.value = entry.recordKey
  emit('inspect-step', entry.step)
}

function sequenceLabel(entry) {
  return entry.sequence == null ? '顺序未记录' : `STEP ${String(entry.sequence).padStart(2, '0')}`
}

function actionLabel(entry) {
  return entry.step.action || entry.meta.description
}

function nodeLabel(entry) {
  const execution = entry.sequence == null ? '执行顺序未记录' : `执行 #${entry.sequence}`
  const call = entry.totalCalls > 1 ? `，第 ${entry.callIndex} 次调用` : ''
  return `${entry.meta.title}，${execution}${call}，${actionLabel(entry)}，${statusLabel(entry.step.status)}，查看执行详情`
}

function isRevision(entry) {
  return entry.meta.key === 'prepare_revision' || entry.meta.key === 'prepare_claim_revision'
}

function hasDuration(step) {
  return formatDuration(step.duration_ms) !== '—'
}

function statusLabel(status) {
  return ({
    running: '进行中', success: '完成', succeeded: '完成', completed: '完成',
    degraded: '降级', failed: '失败', error: '异常', human_review: '待复核',
    skipped: '跳过', pending: '等待中', queued: '排队中',
    cancelled: '已取消', canceled: '已取消', timeout: '超时', blocked: '阻塞',
  }[status] || status || '已记录')
}

function statusTone(status) {
  return ({
    running: 'running', success: 'success', succeeded: 'success', completed: 'success',
    degraded: 'warning', human_review: 'warning', failed: 'danger', error: 'danger',
    timeout: 'danger', blocked: 'warning',
  }[status] || 'neutral')
}

</script>

<style scoped>
.execution-graph {
  --graph-text: #102339;
  --graph-muted: #59697b;
  --graph-accent: #176b70;
  --graph-background: #f5f9fb;
  position: relative;
  min-width: 0;
  padding: 16px 12px;
  border: 1px solid #dbe8ec;
  border-radius: 16px;
  background:
    radial-gradient(ellipse at 0 0, #c9eae630, transparent 52%),
    radial-gradient(ellipse at 100% 100%, #dce9f530, transparent 50%),
    radial-gradient(#698f9c26 0.7px, transparent 0.8px),
    var(--graph-background);
  background-size: auto, auto, 18px 18px, auto;
  box-shadow: inset 0 1px 0 #ffffff, 0 6px 20px #10233905;
  color: var(--graph-text);
  isolation: isolate;
  overflow-anchor: none;
}
.execution-graph-accessible-description {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.execution-graph-plane { position: relative; min-width: 0; }
.execution-graph-connections { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
.execution-graph-connection { --edge-color: #658994; }
.execution-graph-connection.tone-warning { --edge-color: #9d753f; }
.execution-graph-connection.tone-danger { --edge-color: #a75e58; }
.execution-graph-connection.tone-neutral { --edge-color: #6e8296; }
.execution-graph-connection.tone-running { --edge-color: #6588a5; }
.execution-graph-edge-halo { fill: none; stroke: var(--edge-color); stroke-width: 7; opacity: 0.045; }
.execution-graph-edge { fill: none; stroke: var(--edge-color); stroke-width: 1.25; stroke-linecap: round; }
.execution-graph-edge-arrow { fill: none; stroke: var(--edge-color); stroke-width: 1.2; stroke-linecap: round; stroke-linejoin: round; opacity: 0.95; }
.execution-graph-connection.is-active .execution-graph-edge { stroke-dasharray: 5 7; opacity: 0.8; animation: graph-current-flow 2s linear infinite; }
.execution-graph-nodes { position: relative; display: flex; flex-direction: column; gap: 16px; margin: 0; padding: 0; list-style: none; }
.execution-graph-entry { min-width: 0; }
.execution-graph-node {
  --node-status-color: #59697b;
  --node-accent: #607d8c;
  --node-text: var(--graph-text);
  --node-muted: var(--graph-muted);
  --node-sequence: #334a63;
  --node-symbol-surface: #f7fbfc;
  position: relative;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
  min-height: 76px;
  padding: 5px 6px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  box-sizing: border-box;
  color: var(--graph-text);
  font: inherit;
  text-align: left;
}
.execution-graph-node.is-inspectable { cursor: pointer; touch-action: manipulation; transition: background-color 180ms ease, border-color 180ms ease; }
.execution-graph-node.is-inspectable:hover { background: radial-gradient(ellipse at 25% 50%, #176b700b, transparent 85%); }
.execution-graph-node.is-selected { background: radial-gradient(ellipse at 25% 50%, #176b7010, transparent 90%); }
.execution-graph-node:focus-visible { outline: 2px solid #176b70; outline-offset: 2px; background: #176b7008; }
.execution-graph-node.status-success { --node-status-color: #176b70; --node-accent: #176b70; }
.execution-graph-node.status-running { --node-status-color: #256882; --node-accent: #256882; }
.execution-graph-node.status-warning { --node-status-color: #935719; --node-accent: #935719; }
.execution-graph-node.status-danger { --node-status-color: #a1322c; --node-accent: #a1322c; }
.execution-graph-node.is-revision {
  --node-accent: #935719;
  --node-text: #754511;
  --node-muted: #7d5b31;
  --node-sequence: #805119;
  --node-symbol-surface: #fffaf4;
}
.execution-graph-node.is-terminal {
  --node-accent: #216447;
  --node-text: #164d35;
  --node-muted: #3d6552;
  --node-sequence: #216447;
  --node-symbol-surface: #f4fbf6;
}
.execution-graph-node.status-success:is(.is-revision,.is-terminal) { --node-status-color: var(--node-accent); }
.execution-graph-anchor { position: relative; display: flex; align-items: center; justify-content: center; width: 48px; height: 48px; flex-shrink: 0; }
.execution-graph-emblem { display: block; width: 48px; height: 48px; overflow: visible; }
.execution-graph-orbit { stroke: var(--node-accent); stroke-width: 0.7; stroke-dasharray: 3 6; opacity: 0.32; transform-origin: center; }
.execution-graph-hexagon,.execution-graph-terminal-core { fill: var(--node-symbol-surface); stroke: var(--node-accent); stroke-width: 1.2; }
.execution-graph-terminal-orbit { stroke-dasharray: none; opacity: 0.65; }
.execution-graph-facet { stroke: var(--node-accent); stroke-width: 0.6; opacity: 0.18; }
.execution-graph-symbol { stroke: var(--node-accent); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.execution-graph-port { fill: var(--node-accent); }
.execution-graph-node-content { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.execution-graph-node-eyebrow { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; min-width: 0; color: var(--node-muted); font-size: 12px; line-height: 1.4; }
.execution-graph-sequence { color: var(--node-sequence); font: 600 12px/1.4 Consolas, monospace; letter-spacing: 0.04em; }
.execution-graph-call-count { color: var(--node-muted); font-size: 12px; line-height: 1.4; }
.execution-graph-revision-label { color: var(--node-accent); font-size: 12px; line-height: 1.4; }
.execution-graph-node-main { display:flex; align-items:center; gap:8px; min-width:0; }
.execution-graph-node-title { flex: 1 1 auto; min-width: 0; color: var(--node-text); font-size: 14px; font-weight: 700; line-height: 1.55; overflow-wrap: anywhere; }
.execution-graph-action { display: block; flex:1 1 auto; min-width: 0; overflow: hidden; color: var(--node-muted); font-size: 12px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.execution-graph-node-footer { display: grid; grid-template-columns: minmax(0, 1fr) auto 14px; align-items: center; gap: 7px; min-width: 0; padding-top: 2px; color: var(--node-muted); font-size: 12px; line-height: 1.5; }
.execution-graph-status { display: inline-flex; flex:none; align-items: center; gap: 5px; color: var(--node-status-color); font-size:12px; line-height:1.5; }
.execution-graph-status-dot { width: 4px; height: 4px; border-radius: 50%; background: currentColor; }
.execution-graph-duration { grid-column: 2; min-width: 48px; color: var(--node-muted); text-align: right; white-space: nowrap; }
.execution-graph-inspect { grid-column: 3; color: var(--node-accent); }
.is-track-offset .execution-graph-anchor { transform: translateX(12px); }
.is-auxiliary .execution-graph-node { min-height: 68px; }
.is-auxiliary .execution-graph-node-title { font-size: 13px; }
.status-running .execution-graph-orbit { animation: graph-node-pulse 1.8s ease-in-out infinite; }
.execution-graph-empty { display: flex; align-items: center; justify-content: center; gap: 14px; min-height: 110px; color: var(--graph-muted); font-size: 13px; line-height: 1.5; }
.execution-graph-waiting-orbit { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: 1px dashed #607d8c; border-radius: 50%; }
.execution-graph-waiting-orbit span { width: 8px; height: 8px; border: 1px solid #176b70; border-radius: 50%; background: #176b700f; }

@keyframes graph-node-pulse { 0%, 100% { opacity: 0.32; transform: scale(1); } 50% { opacity: 0.85; transform: scale(1.07); } }
@keyframes graph-current-flow { to { stroke-dashoffset: -24; } }
@media (max-width: 480px) {
  .execution-graph { padding: 14px 10px; }
  .execution-graph-node { gap: 10px; padding-inline: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .execution-graph-node { transition: none; }
  .status-running .execution-graph-orbit,
  .execution-graph-connection.is-active .execution-graph-edge { animation: none; }
}
</style>
