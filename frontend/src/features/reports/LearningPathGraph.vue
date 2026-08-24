<template>
  <article class="visual-card path-card" aria-labelledby="path-graph-heading">
    <div class="visual-heading">
      <div><span>LEARNING PATH PLAN</span><h3 id="path-graph-heading">学习路径规划图</h3></div>
      <small>当前节点 {{ data?.current_node_ids?.length || 0 }}</small>
    </div>
    <el-empty v-if="!nodes.length" description="完成方向选择后展示学习路径" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习路径规划图" />
      <p class="summary">补救 {{ summary.remedial_node_count || 0 }} · 待验证 {{ summary.verification_node_count || 0 }} · 可进入下一步 {{ summary.next_node_count || 0 }} · 被阻塞 {{ summary.blocked_node_count || 0 }}</p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, GraphChart, TooltipComponent, LegendComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const nodes = computed(() => props.data?.nodes || [])
const summary = computed(() => props.data?.summary || {})
const colors = Object.freeze({ prerequisite: '#8799ac', current: '#d9a441', remedial: '#d85e4b', next: '#2f78dc', challenge: '#6c74c8', verification: '#a06fc5' })
const labels = Object.freeze({ prerequisite: '前置节点', current: '当前学习', remedial: '补救学习', next: '下一步', challenge: '进阶挑战', verification: '待验证' })

const option = computed(() => ({
  tooltip: { formatter: ({ data }) => {
    const score = typeof data?.mastery_score === 'number' ? `${Math.round(data.mastery_score * 100)}%` : '未测量'
    return `<b>${data?.name || ''}</b><br/>角色：${labels[data?.role] || data?.role}<br/>掌握度：${score}<br/>状态：${data?.progress_status || '—'}${data?.blocked ? `<br/>阻塞于：${(data.blocked_by_node_ids || []).join('、') || '路径状态'}` : ''}`
  } },
  series: [{
    type: 'graph', layout: 'none', roam: true, draggable: false, left: 18, right: 18, top: 28, bottom: 18,
    symbol: 'roundRect', symbolSize: [106, 44], edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 7,
    label: { show: true, color: '#fff', fontSize: 11, overflow: 'truncate', width: 90 },
    lineStyle: { color: '#a9bacb', width: 1.5 },
    data: nodes.value.map((node, index) => ({
      ...node, id: node.skill_node_id, name: node.name,
      x: (node.stable_order || index + 1) * 132,
      y: ({ prerequisite: 46, verification: 104, remedial: 162, current: 220, next: 278, challenge: 336 }[node.role] || 46),
      itemStyle: { color: node.blocked ? '#aeb9c5' : colors[node.role] || colors.prerequisite, borderColor: node.skill_node_id === (props.data?.current_node_ids || [])[0] ? '#18354d' : '#fff', borderWidth: 2 },
    })),
    links: (props.data?.edges || []).map((edge) => ({ source: edge.source_skill_node_id, target: edge.target_skill_node_id, lineStyle: { type: edge.relation === 'prerequisite' ? 'solid' : 'dashed' } })),
  }],
}))
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { padding:6px 8px; border-radius:999px; background:#f2effb; color:#7162a2; font-size:11px; white-space:nowrap; }.chart { height:340px; margin-top:10px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.5; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:300px; } }
</style>
