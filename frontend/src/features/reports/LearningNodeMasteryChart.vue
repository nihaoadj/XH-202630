<template>
  <article class="visual-card" aria-labelledby="node-mastery-heading">
    <div class="visual-heading">
      <div><span>LEARNING NODE MASTERY</span><h3 id="node-mastery-heading">学习节点掌握图</h3></div>
      <small>全部节点 · 按掌握度与证据状态</small>
    </div>
    <el-empty v-if="!nodes.length" description="当前方向还没有可展示的学习节点" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习节点掌握图" />
      <div class="legend" aria-label="学习节点状态图例">
        <span v-for="item in legend" :key="item.status"><i :style="{ background: item.color }" />{{ item.label }}</span>
      </div>
      <p class="summary">共 {{ summary.total_node_count || nodes.length }} 个节点；已测 {{ measuredCount }} 个。未测节点显示“待测”，不等同于 0 分。</p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, DataZoomComponent, GridComponent, TooltipComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const nodes = computed(() => props.data?.nodes || [])
const summary = computed(() => props.data?.summary || {})
const colors = Object.freeze({
  weak: '#d9534f',
  learning: '#d9a441',
  mastered: '#2e9d75',
  self_reported: '#8f7ac6',
  unassessed: '#b8c3cf',
})
const labels = Object.freeze({
  weak: '已验证薄弱',
  learning: '学习中',
  mastered: '已确认掌握',
  self_reported: '自评待验证',
  unassessed: '未测量',
})
const conclusionLabels = Object.freeze({
  unassessed: '尚未测评',
  baseline_observation: '初始基线，待确认',
  awaiting_confirmation: '待第二次正式测评确认',
  confirmed_mastery: '已确认掌握',
  needs_reinforcement: '需巩固并重新测评',
})
const actionLabels = Object.freeze({ learn: '学习节点', remediate: '降阶巩固', practice: '纠错包巩固', verify: '继续测评确认', maintain: '保持与复习' })
const legend = Object.freeze(Object.entries(labels).map(([status, label]) => ({ status, label, color: colors[status] })))
const measuredCount = computed(() => nodes.value.filter((node) => typeof node.mastery_score === 'number').length)

const option = computed(() => {
  const categories = nodes.value.map((node) => node.name)
  const scores = nodes.value.map((node) => {
    const measured = typeof node.mastery_score === 'number'
    return {
      value: measured ? Math.round(node.mastery_score * 100) : 0,
      itemStyle: { color: colors[node.mastery_status] || colors.unassessed, opacity: measured ? 1 : 0.35 },
      label: { show: true, formatter: measured ? `${Math.round(node.mastery_score * 100)}%` : '待测', color: '#536d87', fontSize: 11 },
      node,
    }
  })
  return {
    grid: { top: 18, right: 28, bottom: nodes.value.length > 8 ? 76 : 22, left: 94 },
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => {
        const node = data?.node
        if (!node) return ''
        const score = typeof node.mastery_score === 'number' ? `${Math.round(node.mastery_score * 100)}%` : '待测'
        const latest = typeof node.latest_observed_score === 'number' ? `${Math.round(node.latest_observed_score * 100)}%` : '—'
        return `<b>${node.name}</b><br/>第 ${node.tier || '—'} 阶 · 掌握度：${score}<br/>状态：${labels[node.mastery_status] || node.mastery_status}<br/>结论：${conclusionLabels[node.conclusion] || node.conclusion}<br/>最近一次正式成绩：${latest}<br/>独立测评：${node.independent_session_count || 0} 次 · 证据：${node.objective_evidence_count || 0} 次<br/>下一步：${actionLabels[node.next_action] || node.next_action}`
      },
    },
    xAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#61758c' }, splitLine: { lineStyle: { color: '#e8eef4' } } },
    yAxis: { type: 'category', inverse: true, data: categories, axisLabel: { color: '#61758c', fontSize: 11, width: 82, overflow: 'truncate' }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8e4ee' } } },
    dataZoom: nodes.value.length > 8 ? [{ type: 'slider', yAxisIndex: 0, width: 14, right: 4, start: 0, end: Math.max(25, Math.round(8 / nodes.value.length * 100)) }] : [],
    series: [{ type: 'bar', barMaxWidth: 20, data: scores, showBackground: true, backgroundStyle: { color: '#f2f6fa', borderRadius: 5 }, itemStyle: { borderRadius: [0, 5, 5, 0] } }],
  }
})
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { max-width:190px; overflow:hidden; padding:6px 8px; border-radius:999px; background:#eef5ff; color:#58728d; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.chart { height:350px; margin-top:10px; }.legend { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:6px; color:#62778f; font-size:11px; }.legend span { display:inline-flex; align-items:center; gap:5px; }.legend i { width:9px; height:9px; border-radius:3px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.5; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:330px; } }
</style>
