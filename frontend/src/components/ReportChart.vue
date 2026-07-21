<template>
  <div>
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card>
          <template #header>能力雷达图</template>
          <v-chart class="chart" :option="radarOption" autoresize />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>资源难度匹配曲线</template>
          <v-chart class="chart" :option="lineOption" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 20px;">
      <template #header>知识盲区</template>
      <el-tag v-for="wp in data.weak_points" :key="wp" type="danger" style="margin-right: 10px;">{{ wp }}</el-tag>
    </el-card>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart, LineChart } from 'echarts/charts'
import { PolarComponent, TooltipComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, RadarChart, LineChart, PolarComponent, TooltipComponent, GridComponent])

const props = defineProps({
  data: {
    type: Object,
    default: () => ({}),
  },
})

const radarOption = computed(() => {
  const dims = props.data.radar?.dimensions || []
  const values = props.data.radar?.values || []
  return {
    radar: {
      indicator: dims.map((d) => ({ name: d, max: 100 })),
    },
    series: [{
      type: 'radar',
      data: [{ value: values, name: '能力评估' }],
    }],
  }
})

const lineOption = computed(() => {
  const curve = props.data.difficulty_curve || []
  return {
    xAxis: { type: 'category', data: curve.map((c) => c.topic) },
    yAxis: { type: 'value', max: 100 },
    series: [{
      type: 'line',
      data: curve.map((c) => c.score),
      smooth: true,
    }],
  }
})
</script>

<style scoped>
.chart {
  height: 300px;
}
</style>
