<template>
  <section class="analysis-panel">
    <div class="analysis-heading">
      <div><span class="analysis-kicker">LEARNING ANALYSIS</span><h3>能力与学习匹配</h3></div>
      <span class="analysis-note">数据随学习画像实时更新</span>
    </div>

    <div class="chart-grid">
      <article class="chart-card">
        <div class="chart-card-head"><div><span>能力掌握</span><strong>能力雷达图</strong></div><i class="radar-mark">01</i></div>
        <el-empty v-if="!hasRadar" description="完成诊断后展示能力雷达图" :image-size="58" />
        <v-chart v-else class="chart" :option="radarOption" autoresize />
      </article>
      <article class="chart-card">
        <div class="chart-card-head"><div><span>难度匹配</span><strong>学习节奏曲线</strong></div><i class="line-mark">02</i></div>
        <el-empty v-if="!hasCurve" description="暂无可展示的学习节奏数据" :image-size="58" />
        <v-chart v-else class="chart" :option="lineOption" autoresize />
      </article>
    </div>

    <div class="knowledge-grid">
      <article class="knowledge-card weak"><span class="knowledge-label">TO STRENGTHEN</span><h4>待巩固知识点</h4><div class="tag-list"><span v-for="item in data.weak_points || []" :key="item">{{ item }}</span><em v-if="!(data.weak_points || []).length">暂未发现明显薄弱点</em></div></article>
      <article class="knowledge-card strong"><span class="knowledge-label">YOUR STRENGTHS</span><h4>当前优势能力</h4><div class="tag-list"><span v-for="item in data.strong_points || []" :key="item">{{ item }}</span><em v-if="!(data.strong_points || []).length">完成诊断后展示优势能力</em></div></article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart, LineChart } from 'echarts/charts'
import { PolarComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, RadarChart, LineChart, PolarComponent, TooltipComponent, GridComponent, LegendComponent])

const props = defineProps({ data: { type: Object, default: () => ({}) } })
const dimensions = computed(() => props.data.radar?.dimensions || [])
const values = computed(() => props.data.radar?.values || [])
const curve = computed(() => props.data.difficulty_curve || [])
const hasRadar = computed(() => dimensions.value.length > 0 && values.value.length > 0)
const hasCurve = computed(() => curve.value.length > 0)

const radarOption = computed(() => ({
  tooltip: { trigger: 'item' },
  radar: { center: ['50%', '55%'], radius: '66%', splitNumber: 4, axisName: { color: '#657b94', fontSize: 11 }, splitLine: { lineStyle: { color: '#d9e5ef' } }, splitArea: { areaStyle: { color: ['rgba(243, 249, 255, .7)', 'rgba(255,255,255,.5)'] } }, axisLine: { lineStyle: { color: '#d9e5ef' } }, indicator: dimensions.value.map((name) => ({ name, max: 100 })) },
  series: [{ type: 'radar', symbol: 'circle', symbolSize: 5, lineStyle: { color: '#258fbe', width: 2 }, itemStyle: { color: '#258fbe' }, areaStyle: { color: 'rgba(48, 171, 148, .22)' }, data: [{ value: values.value, name: '当前掌握度' }] }],
}))

const lineOption = computed(() => ({
  tooltip: { trigger: 'axis', valueFormatter: (value) => `${value}%` },
  grid: { top: 20, right: 16, bottom: 32, left: 36 },
  xAxis: { type: 'category', boundaryGap: false, data: curve.value.map((item) => item.topic), axisLine: { lineStyle: { color: '#d6e2ed' } }, axisTick: { show: false }, axisLabel: { color: '#71839a', fontSize: 11, overflow: 'truncate', width: 70 } },
  yAxis: { type: 'value', max: 100, splitNumber: 4, axisLabel: { color: '#71839a', fontSize: 11, formatter: '{value}%' }, splitLine: { lineStyle: { color: '#e5edf4' } } },
  series: [{ type: 'line', smooth: true, data: curve.value.map((item) => item.score), symbol: 'circle', symbolSize: 7, lineStyle: { color: '#2f8ed4', width: 3 }, itemStyle: { color: '#2f8ed4', borderColor: '#fff', borderWidth: 2 }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(45, 161, 204, .28)' }, { offset: 1, color: 'rgba(45, 161, 204, .02)' }] } } }],
}))
</script>

<style scoped>
.analysis-panel { padding:20px; border:1px solid #dbe6f2; border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }.analysis-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:16px; }.analysis-kicker,.knowledge-label { display:block; color:#176f61; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.analysis-heading h3 { margin:7px 0 0; color:#10233f; font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.analysis-note { padding:6px 9px; border-radius:999px; background:#eef7f3; color:#287d66; font-size:12px; font-weight:700; white-space:nowrap; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }.chart-card { min-height:310px; padding:16px; border:1px solid #dfe8f1; border-radius:14px; background:linear-gradient(145deg,#fbfdff,#f6fbf9); }.chart-card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }.chart-card-head span,.chart-card-head strong { display:block; }.chart-card-head span { color:#6d8198; font-size:12px; font-weight:650; }.chart-card-head strong { margin-top:5px; color:#193754; font-size:18px; }.chart-card-head i { display:grid; width:30px; height:30px; place-items:center; border-radius:9px; font-size:12px; font-style:normal; font-weight:800; }.radar-mark { background:#e8f7f1; color:#188066; }.line-mark { background:#eaf3ff; color:#2d70bf; }.chart { height:246px; }.chart-card :deep(.el-empty) { height:230px; }
.knowledge-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin-top:14px; }.knowledge-card { min-width:0; padding:16px; border:1px solid #dfe8f1; border-radius:14px; }.knowledge-card.weak { background:linear-gradient(120deg,#fffaf3,#fffefd); border-color:#f0e0c5; }.knowledge-card.strong { background:linear-gradient(120deg,#f4fbf8,#fbfefd); border-color:#d0e9df; }.knowledge-card.weak .knowledge-label { color:#a86c18; }.knowledge-card.strong .knowledge-label { color:#197c64; }.knowledge-card h4 { margin:8px 0 0; color:#1a3756; font-size:18px; }.tag-list { display:flex; flex-wrap:wrap; gap:8px; margin-top:13px; }.tag-list span { padding:7px 10px; border-radius:999px; background:rgba(255,255,255,.75); color:#596f87; font-size:12px; font-weight:700; }.weak .tag-list span { border:1px solid #f0dfc3; color:#9a671e; }.strong .tag-list span { border:1px solid #cbe7da; color:#1c7c66; }.tag-list em { color:#7d8da0; font-size:13px; font-style:normal; }
@media (max-width:860px) { .chart-grid,.knowledge-grid { grid-template-columns:1fr; }.analysis-panel { padding:18px; } } @media (max-width:560px) { .analysis-heading { flex-direction:column; }.analysis-note { white-space:normal; } }
</style>
