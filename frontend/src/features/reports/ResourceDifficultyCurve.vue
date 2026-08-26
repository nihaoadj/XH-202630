<template>
  <article class="visual-card" aria-labelledby="difficulty-heading">
    <div class="visual-heading">
      <div><span>RESOURCE DIFFICULTY FIT</span><h3 id="difficulty-heading">资源难度匹配曲线</h3></div>
      <small>{{ data?.strategy_version || '未配置策略' }}</small>
    </div>
    <el-empty v-if="!points.length" description="暂无已发布且可关联能力节点的资源" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习者准备度与资源难度对比曲线" />
      <p class="summary">已测匹配 {{ summary.measured_point_count || 0 }} / {{ summary.total_point_count || points.length }}；资源或学习者准备度缺失时不以 0 分替代。</p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const points = computed(() => props.data?.points || [])
const summary = computed(() => props.data?.summary || {})
const statusLabel = Object.freeze({ too_easy: '偏简单', matched: '适配', challenging: '适度挑战', too_hard: '难度过高', not_measured: '未测量' })

const option = computed(() => {
  const categories = points.value.map((point) => `${point.skill_name} · ${point.resource_type}`)
  const readiness = points.value.map((point) => point.learner_readiness_score == null ? null : Math.round(point.learner_readiness_score * 100))
  const difficulty = points.value.map((point) => point.resource_difficulty_score == null ? null : Math.round(point.resource_difficulty_score * 100))
  const lower = points.value.map((point) => point.learner_readiness_score == null ? null : Math.max(0, Math.round((point.learner_readiness_score - .15) * 100)))
  const upper = points.value.map((point) => point.learner_readiness_score == null ? null : Math.min(100, Math.round((point.learner_readiness_score + .10) * 100)))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (items) => {
        const index = items?.[0]?.dataIndex
        const point = points.value[index]
        if (!point) return ''
        const readinessText = point.learner_readiness_score == null ? '未测量' : `${Math.round(point.learner_readiness_score * 100)}%`
        const difficultyText = point.resource_difficulty_score == null ? '未测量' : `${Math.round(point.resource_difficulty_score * 100)}%`
        const gap = point.difficulty_gap == null ? '—' : `${Math.round(point.difficulty_gap * 100)}%`
        return `<b>${point.skill_name}</b><br/>资源：${point.resource_type}<br/>学习者准备度：${readinessText}<br/>资源难度：${difficultyText}<br/>差值：${gap}<br/>结论：${statusLabel[point.match_status] || point.match_status}`
      },
    },
    legend: { bottom: 0, textStyle: { color: '#637990', fontSize: 11 } },
    grid: { top: 30, right: 14, bottom: 48, left: 38 },
    xAxis: { type: 'category', data: categories, axisLabel: { interval: 0, rotate: categories.length > 3 ? 22 : 0, color: '#61758c', fontSize: 10, overflow: 'truncate', width: 82 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8e4ee' } } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#61758c', fontSize: 10 }, splitLine: { lineStyle: { color: '#e8eef4' } } },
    series: [
      { name: '学习者准备度', type: 'line', data: readiness, connectNulls: false, symbolSize: 7, lineStyle: { color: '#2f78dc', width: 3 }, itemStyle: { color: '#2f78dc' } },
      { name: '资源难度', type: 'line', data: difficulty, connectNulls: false, symbolSize: 7, lineStyle: { color: '#e58b39', width: 3 }, itemStyle: { color: '#e58b39' } },
      { name: '适配下界', type: 'line', data: lower, connectNulls: false, symbol: 'none', lineStyle: { color: '#9fc4ef', type: 'dashed' } },
      { name: '适配上界', type: 'line', data: upper, connectNulls: false, symbol: 'none', lineStyle: { color: '#9fc4ef', type: 'dashed' } },
    ],
  }
})
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { max-width:140px; overflow:hidden; padding:6px 8px; border-radius:999px; background:#edf8f4; color:#237d64; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.chart { height:286px; margin-top:10px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.5; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:270px; } }
</style>
