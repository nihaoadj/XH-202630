<template>
  <article class="visual-card path-card" aria-labelledby="path-graph-heading">
    <div class="visual-heading">
      <div><span>LEARNING PATH PLAN</span><h3 id="path-graph-heading">学习路径规划图</h3></div>
      <small>本轮优先 {{ focusNodes.length }}</small>
    </div>
    <el-empty v-if="!nodes.length" description="完成方向选择后展示学习路径" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习路径规划图" />
      <ol v-if="focusNodes.length" class="focus-route" aria-label="本轮优先学习路线">
        <li v-for="node in focusNodes" :key="node.skill_node_id"><b>{{ node.name }}</b><small>{{ labels[node.role] }}</small></li>
      </ol>
      <p class="summary">优先补救 {{ summary.eligible_remedial_node_count ?? summary.remedial_node_count ?? 0 }} · 待验证 {{ summary.verification_node_count || 0 }} · 可学习 {{ summary.next_node_count || 0 }} · 后续受前置限制 {{ summary.blocked_node_count || 0 }}</p>
      <p class="path-note">按学习阶从左到右排列；箭头表示必须先完成的前置能力。亮色节点是本轮优先项，灰色节点留待后续解锁。</p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, GraphChart, TooltipComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const nodes = computed(() => props.data?.nodes || [])
const summary = computed(() => props.data?.summary || {})
const focusIds = computed(() => new Set(props.data?.focus_node_ids || []))
const focusNodes = computed(() => nodes.value.filter((node) => focusIds.value.has(node.skill_node_id)))
const colors = Object.freeze({ prerequisite: '#8799ac', current: '#d9a441', remedial: '#d85e4b', next: '#2f78dc', challenge: '#6c74c8', verification: '#a06fc5' })
const labels = Object.freeze({ prerequisite: '后续学习', current: '当前学习', remedial: '补救学习', next: '下一步', challenge: '进阶挑战', verification: '待验证' })

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
      x: (tierIndex.get(tier) + 1) * 260,
      y: (index + 1) * (maxRows > 4 ? 68 : 92),
    }))
  }
  return positions
})

const option = computed(() => ({
  tooltip: { formatter: ({ data }) => {
    const score = typeof data?.mastery_score === 'number' ? `${Math.round(data.mastery_score * 100)}%` : '未测量'
    const placement = { verification_required: '初始豁免待重新验证', placement_exempt: '初始豁免', formally_reverified: '已完成正式重新验证' }[data?.placement_verification_status]
    return `<b>${data?.name || ''}</b><br/>第 ${data?.tier || '—'} 阶 · ${labels[data?.role] || data?.role}<br/>掌握度：${score}<br/>进度：${data?.progress_status || '—'}${placement ? `<br/>入门判定：${placement}` : ''}${data?.blocked ? `<br/>需先完成：${(data.blocked_by_node_ids || []).join('、') || '前置能力'}` : ''}`
  } },
  series: [{
    type: 'graph', layout: 'none', roam: true, draggable: false, left: 44, right: 36, top: 28, bottom: 18,
    symbol: 'roundRect', symbolSize: [116, 46], edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 7,
    label: { show: true, color: '#fff', fontSize: 11, overflow: 'truncate', width: 98 },
    lineStyle: { color: '#c7d4e1', width: 1.3 },
    data: nodes.value.map((node, index) => {
      const position = layout.value.get(node.skill_node_id) || { x: (index + 1) * 160, y: 80 }
      const isFocus = focusIds.value.has(node.skill_node_id)
      return {
        ...node, id: node.skill_node_id, name: node.name, x: position.x, y: position.y,
        itemStyle: {
          color: node.blocked && !isFocus ? '#aeb9c5' : colors[node.role] || colors.prerequisite,
          opacity: isFocus ? 1 : .72,
          borderColor: isFocus ? '#18354d' : '#fff', borderWidth: isFocus ? 2.5 : 1.5,
        },
      }
    }),
    links: (props.data?.edges || []).map((edge) => {
      const emphasized = focusIds.value.has(edge.source_skill_node_id) || focusIds.value.has(edge.target_skill_node_id)
      return {
        source: edge.source_skill_node_id,
        target: edge.target_skill_node_id,
        lineStyle: { color: emphasized ? '#7fa5cf' : '#d6e0e9', width: emphasized ? 2.2 : 1, opacity: emphasized ? .9 : .5 },
      }
    }),
  }],
}))
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { padding:6px 8px; border-radius:999px; background:#f2effb; color:#7162a2; font-size:11px; white-space:nowrap; }.chart { height:340px; margin-top:10px; }.focus-route { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 0; padding:0; list-style:none; }.focus-route li { display:inline-flex; align-items:center; gap:6px; padding:6px 9px; border:1px solid #d8e6f3; border-radius:999px; background:#f8fbff; color:#294864; font-size:12px; }.focus-route li:not(:last-child)::after { margin-left:4px; color:#8ba2b9; content:'→'; }.focus-route small { color:#6d8198; font-size:11px; }.summary,.path-note { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.5; }.path-note { margin-top:4px; color:#8a9aad; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:300px; } }
</style>
