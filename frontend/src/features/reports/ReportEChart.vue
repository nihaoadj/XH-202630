<template>
  <div ref="host" class="report-echart" :data-chart-state="state" :aria-busy="state === 'pending'">
    <div ref="surface" class="report-echart-surface" />
    <p v-if="state === 'pending'" class="report-echart-state" role="status">正在绘制图表…</p>
    <div v-else-if="state === 'error'" class="report-echart-state" role="alert"><span>图表暂未显示</span><button type="button" @click="retry">重新绘制</button></div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { init, use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'

use([SVGRenderer])
const props = defineProps({ option: { type: Object, required: true }, initOptions: { type: Object, default: () => ({}) }, autoresize: { type: Boolean, default: true } })
const emit = defineEmits(['chart-click'])
const host = ref(null)
const surface = ref(null)
const chart = shallowRef(null)
const state = ref('pending')
let observer
let scheduled = false
let disposed = false
let optionDirty = true
let size = { width: 0, height: 0 }

function draw() {
  if (disposed || !host.value || !surface.value) return
  const width = host.value.clientWidth
  const height = host.value.clientHeight
  if (!width || !height) return
  try {
    if (!chart.value) {
      chart.value = init(surface.value, undefined, { ...props.initOptions, renderer: 'svg', width, height })
      chart.value.on('click', (event) => emit('chart-click', event))
      optionDirty = true
    }
    if (size.width !== width || size.height !== height) chart.value.resize({ width, height })
    size = { width, height }
    if (optionDirty) {
      chart.value.setOption({ ...props.option, animation: false }, { notMerge: true, lazyUpdate: false })
      optionDirty = false
    }
    chart.value.getZr().flush()
    state.value = 'ready'
  } catch (error) {
    chart.value?.dispose()
    chart.value = null
    state.value = 'error'
    console.error('Report chart could not be drawn', error)
  }
}
function schedule() {
  if (disposed || scheduled) return
  scheduled = true
  queueMicrotask(() => { scheduled = false; draw() })
}
function retry() {
  chart.value?.dispose()
  chart.value = null
  state.value = 'pending'
  schedule()
}
function visible() { if (document.visibilityState === 'visible') schedule() }
watch(() => props.option, () => { optionDirty = true; schedule() }, { deep: true, flush: 'post' })
onMounted(async () => {
  await nextTick()
  if (disposed) return
  draw()
  if (props.autoresize && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(schedule)
    observer.observe(host.value)
  }
  window.addEventListener('resize', schedule)
  document.addEventListener('visibilitychange', visible)
})
onBeforeUnmount(() => {
  disposed = true
  observer?.disconnect()
  window.removeEventListener('resize', schedule)
  document.removeEventListener('visibilitychange', visible)
  chart.value?.dispose()
  chart.value = null
})
defineExpose({ chart, resize: schedule, getOption: () => chart.value?.getOption() })
</script>

<style scoped>
.report-echart { position:relative; display:block; width:100%; min-width:0; }
.report-echart-surface { width:100%; height:100%; min-width:0; }
.report-echart-state { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:10px; margin:0; color:#61758c; font-size:13px; }
.report-echart-state button { padding:7px 12px; border:1px solid #b4cbe2; border-radius:7px; color:#315f94; background:#f3f8ff; cursor:pointer; }
</style>
