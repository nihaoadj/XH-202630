<template>
  <article class="visual-card" aria-labelledby="difficulty-heading">
    <div class="visual-heading">
      <div><span>RESOURCE FIT &amp; REVIEW</span><h3 id="difficulty-heading">资源适配与审核</h3></div>
    </div>
    <el-empty v-if="!points.length" description="暂无已发布且可关联能力节点的资源" :image-size="56" />
    <template v-else>
      <v-chart :init-options="initOptions" class="chart" :option="option" autoresize aria-label="难度匹配与审核参考分" />
      <p class="summary">批次均分与单份资源审核分分段绘制。每批的难度匹配度按测评成绩 80%、难度感受 20% 计算。未填写感受时使用测评成绩。</p>
      <p class="summary credibility-summary">普通审核参考 {{ summary.ordinary_review_count || 0 }} 份 · Claim 核验换算 {{ summary.claim_review_scored_count || 0 }} 份<span v-if="summary.claim_review_scored_count"> · Claim 平均 {{ formatScore(summary.average_claim_review_score) }}</span></p>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from './ReportEChart.vue'

use([SVGRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const initOptions = Object.freeze({ renderer: 'svg' })
const props = defineProps({ data: { type: Object, default: () => ({}) } })
const points = computed(() => props.data?.points || [])
const summary = computed(() => props.data?.summary || {})
const unavailableLabels = {
  review_failed: '普通审核未通过',
  review_unverified: '普通审核通过记录未确认',
  claim_unmeasured: 'Claim 核验未完成或缺少完整证据',
  claim_not_applicable: '无可核验事实',
  claim_configuration_unknown: '历史资源缺少 Claim 开关记录',
}
const isBatchAverage = (point) => point?.point_type === 'batch_average'
const isBatchFit = (point) => point?.point_type === 'batch_fit'
const isBatchPoint = point => isBatchAverage(point) || isBatchFit(point)
const pointLabel = (point, index) => {
  if (isBatchFit(point)) return '最新批次'
  if (isBatchAverage(point)) {
    const historyOrdinal = points.value.slice(0, index + 1).filter(isBatchAverage).length
    return `历史批次${String(historyOrdinal).padStart(2, '0')}`
  }
  const name = point.resource_name?.trim()
  const skill = point.skill_name?.trim()
  const labels = [name, skill === '未关联能力节点' ? '' : skill].filter(Boolean)
  return [...new Set(labels)].join(' · ') || point.resource_type || '资源'
}
const formatScore = value => typeof value === 'number' ? `${value} / 100` : '—'
const scale = value => typeof value === 'number' ? Math.round(value * 100) : null

// Share a legend entry per review source while keeping the two levels of detail separate.
function reviewSeries(name, field, color) {
  return [true, false].map(batch => ({
    id: `${field}-${batch ? 'batch' : 'resource'}`,
    name,
    yAxisIndex: 1,
    type: 'line',
    data: points.value.map(point => isBatchPoint(point) === batch ? point[field] ?? null : null),
    symbolSize: 7,
    itemStyle: { color },
    lineStyle: { color },
  }))
}

function crossSourceSeries(reviewPoints) {
  const source = point => {
    const ordinary = typeof point.ordinary_review_score === 'number'
    const claim = typeof point.claim_review_score === 'number'
    if (ordinary === claim) return null
    return ordinary ? 'ordinary_review_score' : 'claim_review_score'
  }
  return reviewPoints.flatMap((left, index) => {
    const right = reviewPoints[index + 1]
    if (!right || isBatchPoint(left) !== isBatchPoint(right)) return []
    const leftSource = source(left)
    const rightSource = source(right)
    if (!leftSource || !rightSource || leftSource === rightSource) return []
    const data = Array(reviewPoints.length).fill(null)
    data[index] = left[leftSource]
    data[index + 1] = right[rightSource]
    return [{
      id: `review-bridge-${index}`, name: '跨来源连线', yAxisIndex: 1, type: 'line',
      data, symbol: 'none', silent: true,
      itemStyle: { color: '#637990' },
      lineStyle: { color: '#637990', type: 'dashed' },
    }]
  })
}

const option = computed(() => {
  const categories = points.value.map((point, index) =>
    isBatchPoint(point) ? pointLabel(point, index) : point.resource_type || point.resource_name || '资源',
  )
  return {
    tooltip: {
      renderMode: 'richText',
      trigger: 'axis',
      formatter: items => {
        const index = items?.[0]?.dataIndex
        const point = points.value[index]
        if (!point) return ''
        const lines = [
          pointLabel(point, index),
          isBatchPoint(point) ? `批次资源：${point.resource_count} 份` : `资源类型：${point.resource_type || '未分类'}`,
        ]
        if (isBatchPoint(point)) {
          lines.push(`批次难度匹配度：${formatScore(point.difficulty_fit_score)}`)
          if (typeof point.feedback_score === 'number') lines.push(`正式测评均分：${scale(point.feedback_score)}%`)
          else lines.push('暂无本批次的正式测评成绩')
          if (typeof point.experience_score === 'number') {
            lines.push(`体验分：${formatScore(point.experience_score)} · ${point.subjective_feedback_count} 次`)
          }
        }
        if (typeof point.ordinary_review_score === 'number') lines.push(`普通审核参考：${formatScore(point.ordinary_review_score)}`)
        if (typeof point.claim_review_score === 'number') lines.push(`Claim 核验换算：${formatScore(point.claim_review_score)}`)
        if (!isBatchFit(point) && point.ordinary_review_score == null && point.claim_review_score == null) {
          lines.push(`审核参考：${unavailableLabels[point.credibility_unavailable_reason] || '暂无可用审核分'}`)
        }
        return lines.join('\n')
      },
    },
    legend: { bottom: 4, type: 'scroll', padding: [0, 8], itemGap: 12, textStyle: { color: '#637990', fontSize: 11 } },
    grid: { top: 38, right: 10, bottom: categories.length > 5 ? 58 : 40, left: 12, containLabel: true },
    xAxis: { type: 'category', data: categories, axisLabel: { interval: 'auto', rotate: categories.length > 5 ? 24 : 0, margin: 10, color: '#61758c', fontSize: 11, overflow: 'truncate', width: 86, hideOverlap: true }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '难度匹配度', min: 0, max: 100 },
      { type: 'value', name: '审核参考分', min: 0, max: 100, splitLine: { show: false } },
    ],
    series: [
      { name: '难度匹配度', type: 'line', data: points.value.map(point => point.difficulty_fit_score ?? null), symbolSize: 7, itemStyle: { color: '#2f78dc' } },
      ...reviewSeries('普通审核参考', 'ordinary_review_score', '#99703f'),
      ...reviewSeries('Claim 核验换算', 'claim_review_score', '#7a5cc7'),
      ...crossSourceSeries(points.value),
    ],
  }
})
</script>

<style scoped>
.visual-card { min-width:0; padding:20px; border:1px solid #dbe6f2; border-radius:16px; background:#fff; box-shadow:0 10px 24px rgba(24,60,96,.05); }.visual-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }.visual-heading span { display:block; color:#2058a7; font-size:11px; font-weight:800; letter-spacing:.09em; }.visual-heading h3 { margin:7px 0 0; color:#193754; font-size:20px; }.chart { height:360px; margin-top:20px; }.summary { margin:10px 0 0; color:#73869a; font-size:12px; line-height:1.55; }.credibility-summary { color:#6d559f; } @media (max-width:560px) { .visual-heading { flex-direction:column; }.chart { height:330px; margin-top:16px; } }
</style>
