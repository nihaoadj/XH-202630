<template>
  <article class="visual-card path-card" aria-labelledby="path-graph-heading">
    <div class="visual-heading">
      <div><span>LEARNING PATH PLAN</span><h3 id="path-graph-heading">学习路径规划图</h3></div>
      <div class="path-heading-actions">
        <small><i></i>{{ nodes.length }} 个节点 · {{ tiers.length }} 个学习阶</small>
        <button v-if="nodes.length" class="path-reset" type="button" @click="resetView">复位</button>
      </div>
    </div>
    <el-empty v-if="!nodes.length" description="完成方向选择后展示学习路径" :image-size="56" />
    <template v-else>
      <div class="path-explorer">
        <div class="path-canvas">
          <div ref="chartFrame" class="chart-frame" role="group" tabindex="0"
               aria-label="学习路径图，方向键选择节点，加号和减号缩放，Escape 复位"
               @keydown="handleChartKey">
            <span class="path-selection-status" role="status">{{ selectedNodeName }}</span>
            <v-chart v-if="chartSize.width && chartSize.height" :key="viewRevision" ref="chartRef" :init-options="initOptions" class="chart" :option="option" autoresize aria-label="学习路径规划图" @chart-click="chartClick" />
          </div>
        </div>
      </div>
      <div class="node-legend" aria-label="学习节点状态说明">
        <span v-for="[key, label] in legend" :key="key">
          <i :style="{ background: palette[key].border }" />{{ label }}
        </span>
      </div>
    </template>
  </article>
</template>

<script>
import { graphic, registerPostUpdate } from 'echarts/core'

const pathSeriesId = 'report-learning-path'

// A clockwise outer rectangle and a counterclockwise card outline leave
// a hole in the clip. Each edge gets only its own two endpoint holes.
const OutsideCard = graphic.extendShape({
  shape: { x: 0, y: 0, width: 0, height: 0 },
  buildPath(ctx, { x, y, width, height }) {
    ctx.rect(-100000, -100000, 200000, 200000)
    const right = x + width
    const bottom = y + height
    const rx = width * 13 / 172
    const ry = height * 13 / 58
    ctx.moveTo(x + rx, y)
    ctx.quadraticCurveTo(x, y, x, y + ry)
    ctx.lineTo(x, bottom - ry)
    ctx.quadraticCurveTo(x, bottom, x + rx, bottom)
    ctx.lineTo(right - rx, bottom)
    ctx.quadraticCurveTo(right, bottom, right, bottom - ry)
    ctx.lineTo(right, y + ry)
    ctx.quadraticCurveTo(right, y, right - rx, y)
    ctx.closePath()
  },
})

function clipEndpointCards(model) {
  const series = model.queryComponents({ mainType: 'series', id: pathSeriesId })[0]
  series?.getGraph().eachEdge((edge) => {
    const line = edge.getGraphicEl()
    if (!line) return

    const clips = [edge.node1, edge.node2].map((node) => {
      const card = node.getGraphicEl()?.getSymbolPath()
      if (!card) return null
      // Initialize the symbol geometry, then measure its fill outline.
      // The stroke bounds can use a stale transform on the first render.
      card.getBoundingRect()
      const bounds = card.path.getBoundingRect()
      // Graph nodes and edges sit in sibling drawing groups under the view.
      bounds.applyTransform(graphic.getTransform(card, line.parent.parent))
      return new OutsideCard({ shape: bounds })
    })
    if (clips[0] && clips[1]) {
      clips[0].setClipPath(clips[1])
      line.setClipPath(clips[0])
    }
  })
}

registerPostUpdate(clipEndpointCards)

</script>

<script setup>
import { computed, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from './ReportEChart.vue'

use([SVGRenderer, GraphChart, TooltipComponent])

const initOptions = Object.freeze({ renderer: 'svg' })
const props = defineProps({ data: { type: Object, default: () => ({}) } })
const chartFrame = ref(null)
const chartSize = ref({ width: 0, height: 0 })
const symbolSize = computed(() => [Math.max(70, Math.min(172, (chartSize.value.width - 40) / Math.max(1, tiers.value.length) - 24)), 58])
// Leave room beyond the symbol for its stroke, focus shadow and hover scale.
const graphGutter = 30
watch(chartFrame, (frame, _previous, onCleanup) => {
  if (!frame) {
    chartSize.value = { width: 0, height: 0 }
    return
  }
  const measure = () => {
    const width = frame.clientWidth
    const height = frame.clientHeight
    if (!width || !height) return
    if (width !== chartSize.value.width || height !== chartSize.value.height) chartSize.value = { width, height }
  }
  measure()
  const observer = new ResizeObserver(measure)
  observer.observe(frame)
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
const nodes = computed(() => props.data?.nodes || [])
const edges = computed(() => {
  const seen = new Set()
  return (props.data?.edges || []).filter((edge) => {
    const key = `${edge.source_skill_node_id}|${edge.target_skill_node_id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const focusIds = computed(() => new Set(props.data?.focus_node_ids || []))
const palette = {
  current: { border: '#a28b79', tint: '#c8b8ab', text: '#503b30' },
  completed: { border: '#29867f', tint: '#70d2ba', text: '#21695e' },
  remedial: { border: '#c65a55', tint: '#f6a09a', text: '#9a433d' },
  next: { border: '#8064a0', tint: '#bca7d7', text: '#50366f' },
  neutral: { border: '#8299b1', tint: '#b9cbdf', text: '#506982' },
}
const legend = [
  ['current', '当前学习'],
  ['completed', '已完成历史 / 初始覆盖'],
  ['remedial', '待补救巩固'],
  ['next', '下一步可选'],
  ['neutral', '未学习 / 后续解锁'],
]
const labels = Object.freeze({ prerequisite: '后续学习', current: '当前学习', remedial: '补救学习', next: '下一步可选', challenge: '后续学习', verification: '待验证' })
// Resource publication means the learner can see the material; it is not
// evidence that the learner completed the node. Only formal curriculum/path
// completion is rendered as the green historical state.
const isCompleted = (node) => node?.progress_status === 'completed'
// Initial placement covers lower tiers without creating a learning batch.
// It is a distinct visual state from both formal completion and an unlocked
// current batch, but uses the historical green treatment for readability.
const isPlacementExempt = (node) => node?.placement_exempt === true && node?.placement_verification_status === 'placement_exempt'
// The backend's batch projection is the only source of truth for the current-batch
// state. Mastery status and role describe other dimensions and must not make a
// node look like it belongs to the newest learning round.
const isCurrent = (node) => node?.is_current_batch === true
// These statuses prove that a resource was exposed or that a verification did
// not pass, but they do not prove formal completion. Keep them distinct from
// both completed history (green) and the latest batch.
const isLearnedIncomplete = (node) => !isCurrent(node) && node?.progress_status === 'verification_pending'
const isExposed = (node) => !isCurrent(node) && node?.progress_status === 'exposed'
const learnedIncompleteLabel = () => '待测评'
const exposedLabel = () => '已发布待学习'
const displayStateLabel = (node) => isCurrent(node)
  ? '当前学习（最新批次）'
  : isPlacementExempt(node) ? '初始评估已覆盖' : isCompleted(node) ? '已完成历史' : node?.blocked ? '后续解锁' : node?.progress_status === 'reinforcement_due' ? '待补救巩固' : isLearnedIncomplete(node) ? learnedIncompleteLabel(node) : isExposed(node) ? exposedLabel(node) : labels[node?.role] || node?.role || '未规划'
const routeLabel = (node) => isCurrent(node)
  ? (isCompleted(node) ? '当前学习 · 已学待巩固' : '当前学习')
  : isPlacementExempt(node) ? '初始评估已覆盖' : isCompleted(node) ? (node.role === 'remedial' ? '已完成 · 待巩固' : '已完成历史') : node.blocked ? '后续解锁' : node.progress_status === 'reinforcement_due' ? '待补救巩固' : isLearnedIncomplete(node) ? learnedIncompleteLabel(node) : isExposed(node) ? exposedLabel(node) : labels[node.role] || node.role

const layout = computed(() => {
  const tiers = [...new Set(nodes.value.map((node) => Number(node.tier) || 99))].sort((a, b) => a - b)
  const tierIndex = new Map(tiers.map((tier, index) => [tier, index]))
  const byTier = new Map(tiers.map((tier) => [tier, []]))
  for (const node of nodes.value) byTier.get(Number(node.tier) || 99).push(node)
  for (const tierNodes of byTier.values()) tierNodes.sort((left, right) => Number(left.stable_order || 0) - Number(right.stable_order || 0))
  const maxRows = Math.max(1, ...[...byTier.values()].map((items) => items.length))
  const positions = new Map()
  for (const [tier, tierNodes] of byTier.entries()) {
    tierNodes.forEach((node, index) => positions.set(node.skill_node_id, {
      x: (tierIndex.get(tier) + 1) * 292,
      y: (index + 1) * (maxRows > 4 ? 76 : 100),
    }))
  }
  return positions
})

const graphBounds = computed(() => {
  const positions = [...layout.value.values()]
  const xs = positions.map((position) => position.x)
  const ys = positions.map((position) => position.y)
  // ECharts expands a zero-span axis by one unit on each side. Match that
  // range so single-node, single-tier and single-row graphs stay centered.
  const spanX = positions.length ? Math.max(...xs) - Math.min(...xs) || 2 : 2
  const spanY = positions.length ? Math.max(...ys) - Math.min(...ys) || 2 : 2
  const availableWidth = Math.max(1, chartSize.value.width - symbolSize.value[0] - graphGutter * 2)
  const availableHeight = Math.max(1, chartSize.value.height - symbolSize.value[1] - graphGutter * 2)
  return {
    left: 'center',
    top: 'middle',
    width: Math.min(availableWidth, spanX * 1.35),
    height: Math.min(availableHeight, spanY * 1.4),
    spanY,
  }
})
const graphBox = computed(() => {
  const { left, top, width, height } = graphBounds.value
  return { left, top, width, height }
})

const chartRef = ref(null)
watch(() => chartRef.value?.chart, (chart, _previous, onCleanup) => {
  if (!chart) return
  const onRoam = (event) => {
    if (!event.zoom) return
    queueMicrotask(() => {
      if (!chart.isDisposed()) clipEndpointCards(chart.getModel())
    })
  }
  chart.on('graphRoam', onRoam)
  onCleanup(() => chart.off('graphRoam', onRoam))
})
const selectedId = ref('')
const viewRevision = ref(0)
const viewport = ref({})
const relatedOnly = ref(false)
const tiers = computed(() => [...new Set(nodes.value.map(node => Number(node.tier) || 99))].sort((a, b) => a - b))
watch(nodes, (items) => {
  if (!items.some(node => node.skill_node_id === selectedId.value)) {
    selectedId.value = (items.find(isCurrent) || items.find(node => focusIds.value.has(node.skill_node_id)) || items[0])?.skill_node_id || ''
    viewport.value = {}
    viewRevision.value++
  }
}, { immediate: true })
const relatedIds = computed(() => {
  const ids = new Set([selectedId.value])
  for (const edge of edges.value) {
    if (edge.source_skill_node_id === selectedId.value) ids.add(edge.target_skill_node_id)
    if (edge.target_skill_node_id === selectedId.value) ids.add(edge.source_skill_node_id)
  }
  return ids
})
const masteryText = (node) => typeof node?.mastery_score === 'number' ? `${Math.round(node.mastery_score * 100)}%` : '待测量'
function nodePalette(node) {
  if (isCurrent(node)) return palette.current
  if (isPlacementExempt(node) || isCompleted(node)) return palette.completed
  if (node.blocked || isExposed(node)) return palette.neutral
  if (node.progress_status === 'reinforcement_due') return palette.remedial
  if (isLearnedIncomplete(node)) return palette.neutral
  if (node.role === 'remedial' || node.role === 'next') return palette[node.role]
  return palette.neutral
}

function rememberView() {
  const series = chartRef.value?.getOption()?.series?.[0]
  if (series) viewport.value = { zoom: series.zoom || 1, ...(series.center ? { center: series.center } : {}) }
}
function selectNode(id) {
  if (!nodes.value.some(node => node.skill_node_id === id)) return
  rememberView()
  selectedId.value = id
  relatedOnly.value = true
}
function chartClick(event) { if (event.dataType === 'node') selectNode(event.data.id) }
function zoomBy(factor) {
  const instance = chartRef.value?.chart
  if (!instance) return
  const zoom = instance.getOption().series[0].zoom || 1
  const next = Math.min(2.5, Math.max(.6, zoom * factor))
  instance.dispatchAction({ type: 'graphRoam', seriesIndex: 0, zoom: next / zoom, originX: chartSize.value.width / 2, originY: chartSize.value.height / 2 })
  instance.getZr().flush()
  rememberView()
}
const selectedNodeName = computed(() => nodes.value.find(node => node.skill_node_id === selectedId.value)?.name || '')
function resetView() {
  selectedId.value = (nodes.value.find(isCurrent) || nodes.value.find(node => focusIds.value.has(node.skill_node_id)) || nodes.value[0])?.skill_node_id || ''
  relatedOnly.value = false
  viewport.value = {}
  viewRevision.value++
}
function handleChartKey(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || !nodes.value.length) return
  if (event.key === 'Escape') resetView()
  else if (event.key === '+' || event.key === '=') zoomBy(1.2)
  else if (event.key === '-') zoomBy(1 / 1.2)
  else {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    if (!step) return
    const index = nodes.value.findIndex(node => node.skill_node_id === selectedId.value)
    selectNode(nodes.value[(index + step + nodes.value.length) % nodes.value.length].skill_node_id)
  }
  event.preventDefault()
}
function glassGradient([highlight, middle, base]) {
  return {
    type: 'linear', x: 0, y: 0, x2: .18, y2: 1,
    colorStops: [
      { offset: 0, color: highlight },
      { offset: .36, color: middle },
      { offset: 1, color: base },
    ],
  }
}
// ECharts rotates middle edge labels to the curve tangent. Center the vector
// on that anchor so the shaft and chevron meet at the same vertical coordinate.
function arrowImage(color, opacity, reversed) {
  const path = reversed ? 'M8 1.7 4.7 5 8 8.3' : 'M4 1.7 7.3 5 4 8.3'
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 10"><path d="${path}" fill="none" stroke="${color}" stroke-opacity="${opacity}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}
const option = computed(() => ({
  tooltip: { renderMode: 'richText', backgroundColor: '#173650', borderWidth: 0, padding: [10, 14], textStyle: { color: '#fff', fontSize: 12 }, formatter: ({ data, dataType }) => dataType === 'node' ? `${data.name}\n${displayStateLabel(data)} · ${masteryText(data)}` : '箭头指向后继学习节点' },
  series: [{
    id: pathSeriesId, type: 'graph', layout: 'none', roam: true, draggable: false, ...graphBox.value, ...viewport.value, scaleLimit: { min: .6, max: 2.5 },
    symbol: 'path://M13 0H159Q172 0 172 13V45Q172 58 159 58H13Q0 58 0 45V13Q0 0 13 0Z',
    symbolKeepAspect: false, symbolSize: symbolSize.value, edgeSymbol: ['none', 'none'],
    label: {
      show: true,
      align: 'center',
      verticalAlign: 'middle',
      formatter: ({ data }) => `{title|${data.name}}\n{state|${routeLabel(data)}}`,
      rich: {
        title: { color: '#173954', fontSize: 13, fontWeight: 650, align: 'center', width: symbolSize.value[0] - 18, overflow: 'truncate', lineHeight: 21 },
        state: { color: '#46627d', fontSize: 11, align: 'center', width: symbolSize.value[0] - 18, overflow: 'truncate', lineHeight: 17 },
      },
    },
    emphasis: { scale: false, lineStyle: { width: 2.9, opacity: 1 } },
    data: nodes.value.map((node, index) => {
      const position = layout.value.get(node.skill_node_id) || { x: (index + 1) * 160, y: 80 }
      const selected = selectedId.value === node.skill_node_id
      const related = relatedOnly.value && relatedIds.value.has(node.skill_node_id)
      const focused = relatedOnly.value && selected
      const dimmed = relatedOnly.value && !related
      const { border, tint, text } = nodePalette(node)
      const current = isCurrent(node)
      return {
        ...node, id: node.skill_node_id, x: position.x, y: position.y,
        itemStyle: {
          color: glassGradient(current ? [
            selected ? '#fcf6f1' : '#fcf6f1b8',
            selected ? '#e6d9cf' : '#e6d9cfa8',
            selected ? tint : `${tint}b8`,
          ] : [
            selected ? '#fffffffa' : '#ffffff83',
            selected ? `${tint}ac` : related ? `${tint}68` : `${tint}48`,
            selected ? tint : related ? `${tint}a0` : `${tint}78`,
          ]),
          borderColor: focused ? text : current ? border : selected ? text : related ? border : `${border}91`,
          borderWidth: focused ? 1.5 : 1,
          opacity: dimmed ? .38 : 1,
          shadowBlur: focused ? 26 : selected ? 22 : related ? 15 : dimmed ? 0 : 10,
          shadowColor: focused ? `${border}a0` : selected ? `${border}82` : related ? `${border}52` : `${border}26`,
          shadowOffsetY: selected ? 3 : 4,
        },
        label: {
          opacity: dimmed ? .48 : 1,
          rich: {
            ...(current ? { title: { color: text } } : {}),
            state: { color: text },
          },
        },
      }
    }),
    links: edges.value.map(edge => {
      const active = edge.source_skill_node_id === selectedId.value || edge.target_skill_node_id === selectedId.value
      const source = layout.value.get(edge.source_skill_node_id)
      const target = layout.value.get(edge.target_skill_node_id)
      const sameColumn = source?.x === target?.x
      const rowDistance = Math.abs(source?.y - target?.y)
      const skipsRow = sameColumn && rowDistance > 100
      // Keep the midpoint chevron outside any intermediate card in the same column.
      const verticalDistance = rowDistance * graphBounds.value.height / graphBounds.value.spanY
      const bend = skipsRow ? (symbolSize.value[0] + 28) / verticalDistance : sameColumn ? .03 : .08
      const color = active ? '#116cbd' : '#789bbd'
      const opacity = active ? 1 : relatedOnly.value ? .17 : .82
      return {
        source: edge.source_skill_node_id,
        target: edge.target_skill_node_id,
        lineStyle: { color, opacity, width: active ? 2.8 : 1.25, curveness: bend },
        label: {
          show: true,
          position: 'middle',
          distance: 0,
          verticalAlign: 'middle',
          formatter: '{arrow| }',
          rich: {
            arrow: {
              width: active ? 15 : 12,
              height: active ? 12.5 : 10,
              backgroundColor: { image: arrowImage(color, opacity, source?.x > target?.x) },
            },
          },
        },
      }
    }),
  }],
}))
</script>

<style scoped>
.path-card { --path-ink:#193b58; --path-blue:#2877be; --path-line:#d5e4f3; min-width:0; }
.visual-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.visual-heading span { color:#527b9d; font-size:11px; letter-spacing:.12em; }
.visual-heading h3 { margin:7px 0 0; color:var(--path-ink); font-size:22px; }
.visual-heading small { display:flex; align-items:center; gap:8px; color:#526f89; font-size:12px; }
.visual-heading small i { display:inline-block; width:7px; height:7px; border-radius:50%; background:#3489cf; box-shadow:0 0 0 4px #3489cf16; }
.path-heading-actions { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
.path-reset { min-height:38px; padding:0 14px; border:1px solid #c6d9eb; border-radius:9px; background:linear-gradient(#fff,#edf5fc); color:#315d82; font:inherit; font-size:12px; cursor:pointer; }
.path-reset:hover { border-color:#87afd3; background:#e9f3fd; }
.path-reset:focus-visible,.chart-frame:focus-visible { outline:2px solid #548ec3; outline-offset:2px; }
.path-selection-status { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
.path-explorer { margin-top:14px; border:1px solid var(--path-line); border-radius:16px; overflow:hidden; background:#f7fbff; }
.path-canvas { display:flex; flex-direction:column; min-width:0; background-image:radial-gradient(#a8c6e14d .8px,transparent .8px),linear-gradient(130deg,#f4f9ff,#fff); background-size:18px 18px,100% 100%; }
.chart-frame { flex:1; position:relative; min-height:446px; }
.chart { position:absolute; inset:0; width:100%; height:100%; }
.node-legend { display:flex; flex-wrap:wrap; gap:10px 18px; padding:15px 0; color:#526d87; font-size:12px; }
.node-legend span { display:flex; align-items:center; gap:6px; }.node-legend i { width:7px; height:7px; border-radius:50%; }
@media(max-width:600px) { .visual-heading { align-items:flex-start; flex-direction:column; }.path-reset { min-height:44px; } }
</style>
