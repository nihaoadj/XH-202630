<template>
  <article class="visual-card" aria-labelledby="blind-spot-heading">
    <div class="visual-heading">
      <div><span>KNOWLEDGE BLIND SPOTS</span><h3 id="blind-spot-heading">知识盲区定位</h3></div>
      <small>按能力维度查看证据</small>
    </div>
    <el-empty v-if="!nodes.length" description="当前方向还没有可定位的知识节点" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="知识盲区热力图" />
      <div class="legend" aria-label="知识状态图例">
        <span v-for="item in legend" :key="item.status"><i :style="{ background: item.color }" />{{ item.label }}</span>
      </div>
      <p class="summary">已测节点 {{ summary.measured_node_count || 0 }} / {{ summary.total_node_count || nodes.length }}；灰色表示尚无足够客观证据，不能视为低分。</p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, HeatmapChart, GridComponent, TooltipComponent, DataZoomComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const nodes = computed(() => props.data?.nodes || [])
const dimensions = computed(() => props.data?.dimensions || [])
const summary = computed(() => props.data?.summary || {})
const colors = Object.freeze({ verified_weak: '#d9534f', learning: '#d9a441', mastered: '#2e9d75', needs_evidence: '#b47ad1', unassessed: '#b8c3cf' })
const labels = Object.freeze({ concept: '概念理解', scenario: '情境应用', misconception: '误区识别', practice: '实践执行' })
const legend = Object.freeze([
  { status: 'verified_weak', label: '已验证薄弱', color: colors.verified_weak },
  { status: 'learning', label: '学习中', color: colors.learning },
  { status: 'mastered', label: '已掌握', color: colors.mastered },
  { status: 'needs_evidence', label: '待补证据', color: colors.needs_evidence },
  { status: 'unassessed', label: '未测量', color: colors.unassessed },
])

const option = computed(() => {
  const nodeIndex = new Map(nodes.value.map((node, index) => [node.skill_node_id, index]))
  const dimensionIndex = new Map(dimensions.value.map((dimension, index) => [dimension, index]))
  const cells = (props.data?.cells || []).flatMap((cell) => {
    const x = nodeIndex.get(cell.skill_node_id)
    const y = dimensionIndex.get(cell.dimension)
    if (x === undefined || y === undefined) return []
    return [{
      value: [x, y, typeof cell.score === 'number' ? Math.round(cell.score * 100) : -1],
      itemStyle: { color: colors[cell.status] || colors.unassessed, borderColor: '#fff', borderWidth: 2 },
      cell,
    }]
  })
  return {
    tooltip: {
      position: 'top',
      formatter: ({ data }) => {
        const cell = data?.cell
        if (!cell) return ''
        const node = nodes.value.find((item) => item.skill_node_id === cell.skill_node_id)
        const score = typeof cell.score === 'number' ? `${Math.round(cell.score * 100)}%` : '未测量'
        return `<b>${node?.name || cell.skill_node_id}</b><br/>${labels[cell.dimension] || cell.dimension}：${score}<br/>状态：${legend.find((item) => item.status === cell.status)?.label || cell.status}<br/>客观证据：${cell.objective_evidence_count}`
      },
    },
    grid: { top: 18, right: 12, bottom: nodes.value.length > 6 ? 88 : 58, left: 88 },
    xAxis: { type: 'category', data: nodes.value.map((node) => node.name), axisLabel: { interval: 0, rotate: nodes.value.length > 5 ? 28 : 0, color: '#61758c', fontSize: 11, overflow: 'truncate', width: 74 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8e4ee' } } },
    yAxis: { type: 'category', data: dimensions.value.map((dimension) => labels[dimension] || dimension), axisLabel: { color: '#61758c', fontSize: 11 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8e4ee' } } },
    dataZoom: nodes.value.length > 7 ? [{ type: 'slider', xAxisIndex: 0, height: 16, bottom: 12, start: 0, end: Math.max(25, Math.round(7 / nodes.value.length * 100)) }] : [],
    series: [{ type: 'heatmap', data: cells, label: { show: true, color: '#18354d', fontSize: 10, formatter: ({ data }) => typeof data?.cell?.score === 'number' ? `${Math.round(data.cell.score * 100)}%` : '—' }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(20, 55, 85, .22)' } } }],
  }
})
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { padding:6px 8px; border-radius:999px; background:#eef5ff; color:#58728d; font-size:11px; white-space:nowrap; }.chart { height:286px; margin-top:10px; }.legend { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:6px; color:#62778f; font-size:11px; }.legend span { display:inline-flex; align-items:center; gap:5px; }.legend i { width:9px; height:9px; border-radius:3px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.5; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:270px; } }
</style>
