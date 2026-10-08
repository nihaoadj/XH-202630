<template>
  <article class="visual-card path-card" aria-labelledby="path-graph-heading">
    <div class="visual-heading">
      <div><span>LEARNING PATH PLAN</span><h3 id="path-graph-heading">学习路径规划图</h3></div>
      <small><i></i>本轮优先 {{ focusNodes.length }}</small>
    </div>
    <el-empty v-if="!nodes.length" description="完成方向选择后展示学习路径" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习路径规划图" />
      <div class="node-legend" aria-label="学习节点状态说明">
        <span class="legend-current"><i></i>当前学习</span>
        <span class="legend-completed"><i></i>已完成历史（非本轮）</span>
        <span class="legend-learned-incomplete"><i></i>已学未完成</span>
        <span class="legend-remedial"><i></i>待补救巩固</span>
        <span class="legend-next"><i></i>下一步</span>
        <span class="legend-locked"><i></i>未学习 / 后续解锁</span>
      </div>
      <ol v-if="focusNodes.length" class="focus-route" aria-label="本轮优先学习路线">
        <li v-for="node in focusNodes" :key="node.skill_node_id"><b>{{ node.name }}</b><small>{{ routeLabel(node) }}</small></li>
      </ol>
      <p class="summary">优先补救 {{ summary.eligible_remedial_node_count ?? summary.remedial_node_count ?? 0 }} · 待验证 {{ summary.verification_node_count || 0 }} · 可学习 {{ summary.next_node_count || 0 }} · 后续受前置限制 {{ summary.blocked_node_count || 0 }}</p>
      <p class="path-note">按学习阶从左到右排列；箭头表示必须先完成的能力。已完成节点与当前学习节点使用不同颜色。</p>
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
const edges = computed(() => {
  const seen = new Set()
  return (props.data?.edges || []).filter((edge) => {
    const key = `${edge.source_skill_node_id}|${edge.target_skill_node_id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const summary = computed(() => props.data?.summary || {})
const focusIds = computed(() => new Set(props.data?.focus_node_ids || []))
const focusNodes = computed(() => nodes.value.filter((node) => focusIds.value.has(node.skill_node_id)))
const colors = Object.freeze({ prerequisite: '#6f8297', current: '#f0a33a', learnedIncomplete: '#8b6fc4', remedial: '#e66557', next: '#4f8dcc', challenge: '#6875db', verification: '#9aaabd', exposed: '#9aaabd' })
const labels = Object.freeze({ prerequisite: '后续学习', current: '当前学习', remedial: '补救学习', next: '下一步', challenge: '进阶挑战', verification: '待验证' })
// Resource publication means the learner can see the material; it is not
// evidence that the learner completed the node. Only formal curriculum/path
// completion is rendered as the green historical state.
const isCompleted = (node) => node?.progress_status === 'completed'
// Initial placement covers lower tiers without creating a learning batch.
// It is a distinct visual state from both formal completion and an unlocked
// current batch, but uses the historical green treatment for readability.
const isPlacementExempt = (node) => node?.placement_exempt === true && node?.placement_verification_status === 'placement_exempt'
// The backend's batch projection is the only source of truth for the yellow
// state. Mastery status and role describe other dimensions and must not make a
// node look like it belongs to the newest learning round.
const isCurrent = (node) => node?.is_current_batch === true
// These statuses prove that a resource was exposed or that a verification did
// not pass, but they do not prove formal completion. Keep them distinct from
// both completed history (green) and the latest batch (yellow).
const isLearnedIncomplete = (node) => !isCurrent(node) && node?.progress_status === 'verification_pending'
const isExposed = (node) => !isCurrent(node) && node?.progress_status === 'exposed'
const learnedIncompleteLabel = () => '已学习待验证'
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

const option = computed(() => ({
  tooltip: { backgroundColor: 'rgba(15, 32, 56, .96)', padding: [10, 13], borderWidth: 0, borderRadius: 10, textStyle: { color: '#eef6ff', fontSize: 12, lineHeight: 19 }, formatter: ({ data }) => {
    const score = typeof data?.mastery_score === 'number' ? `${Math.round(data.mastery_score * 100)}%` : '未测量'
    const placement = { verification_required: '初始豁免待重新验证', placement_exempt: '初始豁免', formally_reverified: '已完成正式重新验证' }[data?.placement_verification_status]
    const lockReason = data?.reason_codes?.includes('TIER_NOT_UNLOCKED') ? `第 ${data?.tier || '—'} 阶尚未解锁` : `需先完成：${(data?.blocked_by_node_ids || []).join('、') || '前置能力'}`
    return `<b>${data?.name || ''}</b><br/>显示状态：${displayStateLabel(data)}<br/>第 ${data?.tier || '—'} 阶 · ${labels[data?.role] || data?.role}<br/>掌握度：${score}<br/>进度：${data?.progress_status || '—'}${placement ? `<br/>入门判定：${placement}` : ''}${data?.blocked ? `<br/>${lockReason}` : ''}`
  } },
  series: [{
    type: 'graph', layout: 'none', roam: true, draggable: false, left: 48, right: 44, top: 34, bottom: 22,
    symbol: 'roundRect', symbolSize: [136, 54], edgeSymbol: ['none', 'arrow'], edgeSymbolSize: [0, 8],
    label: { show: true, formatter: ({ data }) => data.name, color: '#fff', fontSize: 12, fontWeight: 700, overflow: 'truncate', width: 112, opacity: 1 },
    lineStyle: { color: '#b7c9dc', width: 1.5, opacity: .78 },
    emphasis: { focus: 'adjacency', scale: 1.05, lineStyle: { width: 2.5, opacity: 1 }, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(24, 54, 85, .20)' } },
    data: nodes.value.map((node, index) => {
      const position = layout.value.get(node.skill_node_id) || { x: (index + 1) * 160, y: 80 }
      const isFocus = focusIds.value.has(node.skill_node_id)
      const completed = isCompleted(node)
      const placementExempt = isPlacementExempt(node)
      const current = isCurrent(node)
      const learnedIncomplete = isLearnedIncomplete(node)
      return {
        ...node, id: node.skill_node_id, name: node.name, learningState: current ? 'current' : placementExempt ? 'placement_exempt' : completed ? 'completed' : learnedIncomplete ? 'learned_incomplete' : node.progress_status === 'exposed' ? 'exposed' : 'other', x: position.x, y: position.y,
        itemStyle: {
          color: current ? colors.current : placementExempt ? '#548b88' : completed ? '#548b88' : node.progress_status === 'reinforcement_due' ? colors.remedial : learnedIncomplete ? colors.learnedIncomplete : isExposed(node) ? colors.exposed : node.blocked && !isFocus ? '#9aaabd' : (node.role === 'current' ? colors.prerequisite : colors[node.role] || colors.prerequisite),
          opacity: 1,
          borderColor: completed && node.role === 'remedial' ? '#e66557' : isFocus ? '#ffffff' : 'rgba(255,255,255,.72)', borderWidth: completed && node.role === 'remedial' ? 2.5 : isFocus ? 2.5 : 1,
          shadowBlur: isFocus ? 10 : 2, shadowColor: isFocus ? `${colors[node.role] || colors.prerequisite}55` : 'rgba(18, 42, 71, .10)', shadowOffsetY: 2,
        },
      }
    }),
    links: edges.value.map((edge) => {
      const emphasized = focusIds.value.has(edge.source_skill_node_id) || focusIds.value.has(edge.target_skill_node_id)
      return {
        source: edge.source_skill_node_id,
        target: edge.target_skill_node_id,
        lineStyle: { color: emphasized ? '#5f9bd3' : '#cad7e4', width: emphasized ? 2.5 : 1.15, opacity: emphasized ? 1 : .56 },
      }
    }),
  }],
}))
</script>

<style scoped>
.visual-card { position:relative; min-width:0; overflow:hidden; padding:24px; border:1px solid #dbe8f5; border-radius:22px; background:linear-gradient(145deg,#fff 0%,#f8fbff 100%); box-shadow:0 16px 44px rgba(29,67,110,.10); }.visual-card::before { position:absolute; top:-105px; right:-80px; width:270px; height:270px; border-radius:50%; background:radial-gradient(circle,rgba(69,137,204,.13),transparent 68%); content:''; pointer-events:none; }.visual-heading { position:relative; display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#3476b9; font-size:11px; font-weight:800; letter-spacing:.13em; }.visual-heading h3 { margin:8px 0 0; color:#142d4a; font-size:22px; font-weight:800; letter-spacing:-.035em; }.visual-heading small { display:inline-flex; align-items:center; gap:6px; padding:7px 10px; border:1px solid #e6defa; border-radius:999px; background:#f7f3ff; color:#7657aa; font-size:12px; font-weight:700; white-space:nowrap; }.visual-heading small i { width:6px; height:6px; border-radius:50%; background:#a46bd4; box-shadow:0 0 0 4px rgba(164,107,212,.13); }.chart { position:relative; height:352px; margin-top:13px; border:1px solid rgba(211,226,240,.74); border-radius:16px; background:linear-gradient(180deg,rgba(247,251,255,.88),rgba(255,255,255,.58)); }.node-legend { position:relative; display:flex; flex-wrap:wrap; gap:12px; margin:12px 2px 0; color:#637d95; font-size:11px; font-weight:650; }.node-legend span { display:inline-flex; align-items:center; gap:5px; }.node-legend i { width:8px; height:8px; border-radius:50%; }.legend-current i { background:#f0a33a; }.legend-completed i { background:#548b88; }.legend-learned-incomplete i { background:#8b6fc4; }.legend-remedial i { background:#e66557; }.legend-next i { background:#4f8dcc; }.legend-locked i { background:#9aaabd; }.focus-route { position:relative; display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 0; padding:0; list-style:none; }.focus-route li { display:inline-flex; align-items:center; gap:6px; padding:7px 10px; border:1px solid #dce8f5; border-radius:10px; background:#fff; color:#234664; font-size:12px; font-weight:650; box-shadow:0 3px 10px rgba(36,75,114,.05); }.focus-route li:not(:last-child)::after { margin-left:5px; color:#75a2cb; content:'→'; }.focus-route small { color:#6f879e; font-size:11px; font-weight:500; }.summary,.path-note { position:relative; margin:12px 0 0; color:#607890; font-size:12px; line-height:1.6; }.path-note { margin-top:4px; color:#8a9cb0; } @media (max-width:560px) { .visual-card { padding:18px; border-radius:18px; }.visual-heading { flex-direction:column; }.chart { height:300px; } }
</style>
