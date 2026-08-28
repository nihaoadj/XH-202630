<template>
  <article class="visual-card" aria-labelledby="difficulty-heading">
    <div class="visual-heading">
      <div><span>RESOURCE DIFFICULTY FIT</span><h3 id="difficulty-heading">资源难度匹配曲线</h3></div>
      <small>{{ data?.strategy_version || '未配置策略' }}</small>
    </div>
    <el-empty v-if="!points.length" description="暂无已发布且可关联能力节点的资源" :image-size="56" />
    <template v-else>
      <v-chart class="chart" :option="option" autoresize aria-label="学习者准备度、资源难度与资源可信度对比曲线" />
      <p class="summary">已测匹配 {{ summary.measured_point_count || 0 }} / {{ summary.total_point_count || points.length }} 个点 · 共 {{ summary.total_resource_count || points.length }} 个资源；历史批次按平均值汇总。</p>
      <p v-if="hasCredibility" class="summary credibility-summary">平均可信度 {{ formatScore(summary.average_credibility_score) }} · 已量化 {{ summary.credibility_scored_count || 0 }} · Claim 通过 {{ summary.claim_review_passed_count || 0 }} · 受 80 分上限约束 {{ summary.claim_ceiling_applied_count || 0 }}</p>
      <p v-else class="summary credibility-summary">暂无可量化可信度证据。</p>
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
const credibilityLabels = Object.freeze({ attention: '需关注', high: '高可信', good: '较高可信', moderate: '中等可信', low: '低可信', insufficient_evidence: '证据不足' })
const hasCredibility = computed(() => points.value.some((point) => typeof point.credibility_score === 'number'))
const isBatchAverage = (point) => point?.point_type === 'batch_average'
const pointLabel = (point, index) => {
  if (isBatchAverage(point)) {
    const historyOrdinal = points.value.slice(0, index + 1).filter(isBatchAverage).length
    return `历史批次${String(historyOrdinal).padStart(2, '0')}`
  }
  const name = point.resource_name || point.resource_type || '资源'
  const skill = point.skill_name && point.skill_name !== '未关联能力节点' ? point.skill_name : ''
  return skill ? `${name} · ${skill}` : name
}
// Keep the server's complete audit score intact, but avoid presenting absolute
// certainty in the learner-facing report.
const displayCredibilityScore = (value) => typeof value === 'number' ? Math.min(99, Math.round(value)) : null
const formatScore = (value) => {
  const score = displayCredibilityScore(value)
  return score == null ? '—' : `${score} / 100`
}
const feedbackScoreText = (value) => value == null ? '—' : `${Math.round(value * 100)}%`

const option = computed(() => {
  const categories = points.value.map(pointLabel)
  const readiness = points.value.map((point) => point.learner_readiness_score == null ? null : Math.round(point.learner_readiness_score * 100))
  const difficulty = points.value.map((point) => point.resource_difficulty_score == null ? null : Math.round(point.resource_difficulty_score * 100))
  const credibility = points.value.map((point) => displayCredibilityScore(point.credibility_score))
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
        const breakdown = point.credibility_score_breakdown
        const credibilityText = formatScore(point.credibility_score) === '—' ? '证据不足' : formatScore(point.credibility_score)
        if (isBatchAverage(point)) {
          const label = pointLabel(point, index)
          const calibration = point.difficulty_source === 'calibrated_history'
            ? `<br/>反馈均分：${feedbackScoreText(point.feedback_score)}<br/>反馈校准：+${Math.round((point.difficulty_adjustment || 0) * 100)}%`
            : ''
          return `<b>${label}</b><br/>包含资源：${point.resource_count || point.resource_ids?.length || 0} 个<br/>学习者准备度均值：${readinessText}<br/>资源难度均值：${difficultyText}<br/>差值均值：${gap}${calibration}<br/>结论：${statusLabel[point.match_status] || point.match_status}<br/>资源可信度均值：${credibilityText}`
        }
        const calibration = point.difficulty_source === 'calibrated_history'
          ? `<br/>默认难度：${point.default_resource_difficulty_score == null ? '—' : `${Math.round(point.default_resource_difficulty_score * 100)}%`}<br/>反馈均分：${feedbackScoreText(point.feedback_score)}<br/>反馈校准：+${Math.round((point.difficulty_adjustment || 0) * 100)}%`
          : ''
        const credibilityLines = breakdown
          ? `<br/>资源可信度：${credibilityText}<br/>可信等级：${credibilityLabels[point.credibility_level] || point.credibility_level || '—'}<br/>普通审核：${breakdown.publication_review_score} / 40<br/>来源验证：${breakdown.source_traceability_score} / 50<br/>Claim 审核：${breakdown.claim_review_score} / 10${breakdown.claim_review_passed ? '' : '<br/>Claim 未完全通过：最高 80 分'}<br/>原始审核等级：${point.credibility_grade || '—'}`
          : `<br/>资源可信度：${credibilityText}`
        return `<b>${point.skill_name}</b><br/>资源：${point.resource_type}<br/>学习者准备度：${readinessText}<br/>资源难度：${difficultyText}${calibration}<br/>差值：${gap}<br/>结论：${statusLabel[point.match_status] || point.match_status}${credibilityLines}`
      },
    },
    legend: { bottom: 4, type: 'scroll', padding: [0, 8], itemGap: 12, textStyle: { color: '#637990', fontSize: 11 } },
    grid: { top: 30, right: 18, bottom: categories.length > 4 ? 88 : 68, left: 42, containLabel: true },
    xAxis: { type: 'category', data: categories, axisLabel: { interval: 0, rotate: categories.length > 3 ? 28 : 0, margin: 13, color: '#61758c', fontSize: 10, overflow: 'truncate', width: 86, formatter: (value) => value.length > 14 ? `${value.slice(0, 13)}…` : value }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8e4ee' } } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#61758c', fontSize: 10 }, splitLine: { lineStyle: { color: '#e8eef4' } } },
    series: [
      { name: '学习者准备度', type: 'line', data: readiness, connectNulls: false, symbolSize: 7, lineStyle: { color: '#2f78dc', width: 3 }, itemStyle: { color: '#2f78dc' } },
      { name: '资源难度', type: 'line', data: difficulty, connectNulls: false, symbolSize: 7, lineStyle: { color: '#e58b39', width: 3 }, itemStyle: { color: '#e58b39' } },
      { name: '资源可信度', type: 'line', data: credibility, connectNulls: false, symbolSize: 7, lineStyle: { color: '#7a5cc7', width: 3 }, itemStyle: { color: '#7a5cc7' } },
    ],
  }
})
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.visual-heading small { max-width:140px; overflow:hidden; padding:6px 8px; border-radius:999px; background:#edf8f4; color:#237d64; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.chart { height:330px; margin-top:10px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.55; }.credibility-summary { color:#6d559f; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:320px; } }
</style>
