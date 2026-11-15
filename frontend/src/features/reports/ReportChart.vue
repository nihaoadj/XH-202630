<template>
  <section class="analysis-panel">
    <div class="analysis-heading">
      <div><span class="analysis-kicker">LEARNING ANALYSIS</span><h3>能力雷达图</h3></div>
      <span class="analysis-note">数据随学习画像实时更新</span>
    </div>

    <div class="chart-grid">
      <article class="chart-card">
        <el-empty v-if="!hasRadar" description="完成诊断后展示能力雷达图" :image-size="58" />
        <v-chart :init-options="initOptions" v-else class="chart" :option="radarOption" autoresize />
        <p v-if="hasSelfReported" class="radar-note">图中“自评待验证”节点保留当前估计值，但尚无客观测评证据，可信度较低。</p>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { RadarChart } from 'echarts/charts'
import { PolarComponent, TooltipComponent } from 'echarts/components'
import VChart from './ReportEChart.vue'

use([SVGRenderer, RadarChart, PolarComponent, TooltipComponent])

const initOptions = Object.freeze({ renderer: 'svg' })
const props = defineProps({ data: { type: Object, default: () => ({}) } })
const dimensions = computed(() => props.data.radar?.dimensions || [])
const values = computed(() => props.data.radar?.values || [])
const radarStatuses = computed(() => props.data.radar?.measurement_statuses || [])
const hasRadar = computed(() => dimensions.value.length > 0 && values.value.length > 0)
const hasSelfReported = computed(() => radarStatuses.value.includes('self_reported'))
const statusLabels = Object.freeze({ measured: '已测量', self_reported: '自评待验证（低可信）', unassessed: '未测量' })
const axisName = (name, status) => status === 'self_reported' ? `${name}\n自评待验证` : status === 'unassessed' ? `${name}\n未测量` : name

const radarOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: () => dimensions.value.map((name, index) => {
      const status = radarStatuses.value[index] || 'unassessed'
      const score = status === 'unassessed' ? '—' : `${values.value[index]}%`
      return `${name}：${score}（${statusLabels[status] || status}）`
    }).join('<br/>'),
  },
  radar: { center: ['50%', '50%'], radius: '66%', splitNumber: 4, axisName: { color: '#657b94', fontSize: 11 }, splitLine: { lineStyle: { color: '#d9e5ef' } }, splitArea: { areaStyle: { color: ['rgba(243, 249, 255, .7)', 'rgba(255,255,255,.5)'] } }, axisLine: { lineStyle: { color: '#d9e5ef' } }, indicator: dimensions.value.map((name, index) => ({ name: axisName(name, radarStatuses.value[index] || 'unassessed'), max: 100 })) },
  series: [{ type: 'radar', symbol: 'circle', symbolSize: 5, lineStyle: { color: '#2058a7', width: 2 }, itemStyle: { color: '#2058a7' }, areaStyle: { color: 'rgba(48, 171, 148, .22)' }, data: [{ value: values.value, name: '当前掌握度' }] }],
}))

</script>

<style scoped>
.analysis-panel { padding:20px; border:1px solid #dbe6f2; border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }.analysis-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:16px; }.analysis-kicker { display:block; color:#2058a7; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.analysis-heading h3 { margin:7px 0 0; color:#10233f; font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.analysis-note { padding:6px 9px; border-radius:999px; background:#edf4ff; color:#2058a7; font-size:12px; font-weight:700; white-space:nowrap; }.radar-note { margin:0 4px; color:#866c2b; font-size:12px; line-height:1.5; }
.chart-grid { display:grid; grid-template-columns:1fr; gap:14px; }.chart-card { min-height:310px; padding:16px; border:1px solid #dfe8f1; border-radius:14px; background:linear-gradient(145deg,#fbfdff,#f6fbf9); }.chart { height:360px; }.chart-card :deep(.el-empty) { height:230px; }
@media (max-width:860px) { .chart-grid { grid-template-columns:1fr; }.analysis-panel { padding:18px; } } @media (max-width:560px) { .analysis-heading { flex-direction:column; }.analysis-note { white-space:normal; } }
</style>
